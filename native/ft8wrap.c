/* Interface simples para Python (ctypes) sobre a ft8_lib (MIT, kgoba). */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>

#include "ft8_lib/ft8/decode.h"
#include "ft8_lib/ft8/encode.h"
#include "ft8_lib/ft8/message.h"
#include "ft8_lib/ft8/constants.h"
#include "ft8_lib/common/monitor.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define MAX_CANDIDATES 140
#define MAX_DECODED 60
#define LDPC_ITER 25
#define HASH_SIZE 256

static struct { char call[12]; uint32_t hash; } htab[HASH_SIZE];

static void ht_add(const char* call, uint32_t hash)
{
    int i = (int)((((hash >> 12) & 0x3FFu) * 23) % HASH_SIZE);
    while (htab[i].call[0]) {
        if ((htab[i].hash & 0x3FFFFFu) == hash && !strcmp(htab[i].call, call)) return;
        i = (i + 1) % HASH_SIZE;
    }
    strncpy(htab[i].call, call, 11);
    htab[i].call[11] = 0;
    htab[i].hash = hash;
}

static bool ht_lookup(ftx_callsign_hash_type_t type, uint32_t hash, char* call)
{
    uint8_t shift = (type == FTX_CALLSIGN_HASH_10_BITS) ? 12 : (type == FTX_CALLSIGN_HASH_12_BITS ? 10 : 0);
    int i = (int)(((hash >> (12 - shift)) & 0x3FFu) * 23 % HASH_SIZE);
    while (htab[i].call[0]) {
        if (((htab[i].hash & 0x3FFFFFu) >> shift) == hash) { strcpy(call, htab[i].call); return true; }
        i = (i + 1) % HASH_SIZE;
    }
    call[0] = 0;
    return false;
}

static ftx_callsign_hash_interface_t hash_if = { .lookup_hash = ht_lookup, .save_hash = ht_add };

/* Decodifica um slot inteiro (samples mono, float -1..1). Cada linha de saída:
   "snr\tdt\tfreq\ttexto\n". Retorna o número de mensagens ou -1. protocol: 0 = FT8, 1 = FT4. */
EXPORT int ftx_decode_slot(const float* samples, int n, int sample_rate, int protocol, char* out, int out_size)
{
    monitor_config_t cfg = { .f_min = 200, .f_max = 3000, .sample_rate = sample_rate, .time_osr = 2, .freq_osr = 2,
                             .protocol = protocol ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8 };
    monitor_t mon;
    monitor_init(&mon, &cfg);
    for (int pos = 0; pos + mon.block_size <= n; pos += mon.block_size)
        monitor_process(&mon, samples + pos);

    ftx_candidate_t cands[MAX_CANDIDATES];
    int nc = ftx_find_candidates(&mon.wf, MAX_CANDIDATES, cands, 10);
    static ftx_message_t decoded[MAX_DECODED];
    int nd = 0, written = 0;
    out[0] = 0;
    for (int c = 0; c < nc; ++c) {
        ftx_message_t msg;
        ftx_decode_status_t st;
        if (!ftx_decode_candidate(&mon.wf, &cands[c], LDPC_ITER, &msg, &st)) continue;
        int dup = 0;
        for (int k = 0; k < nd; ++k)
            if (decoded[k].hash == msg.hash && !memcmp(decoded[k].payload, msg.payload, sizeof(msg.payload))) { dup = 1; break; }
        if (dup || nd >= MAX_DECODED) continue;
        decoded[nd++] = msg;
        char text[FTX_MAX_MESSAGE_LENGTH];
        ftx_message_offsets_t offs;
        if (ftx_message_decode(&msg, &hash_if, text, &offs) != FTX_MESSAGE_RC_OK) continue;
        float freq = (mon.min_bin + cands[c].freq_offset + (float)cands[c].freq_sub / mon.wf.freq_osr) / mon.symbol_period;
        float dt = (cands[c].time_offset + (float)cands[c].time_sub / mon.wf.time_osr) * mon.symbol_period;
        float snr = cands[c].score * 0.5f - 24.0f;  /* estimativa aproximada */
        int w = snprintf(out + written, out_size - written, "%.0f\t%.2f\t%.0f\t%s\n", snr, dt, freq, text);
        if (w < 0 || w >= out_size - written) break;
        written += w;
    }
    monitor_free(&mon);
    return nd;
}

#define FT8_BT 2.0f
#define FT4_BT 1.0f

static void synth(const uint8_t* sym, int nsym, float f0, float bt, float period, int rate, float* sig)
{
    int sp = (int)(0.5f + rate * period), nwave = nsym * sp;
    float dphi_peak = 2 * (float)M_PI / sp;
    float* dphi = malloc(sizeof(float) * (nwave + 2 * sp));
    float* pulse = malloc(sizeof(float) * 3 * sp);
    for (int i = 0; i < nwave + 2 * sp; ++i) dphi[i] = 2 * (float)M_PI * f0 / rate;
    for (int i = 0; i < 3 * sp; ++i) {
        float t = i / (float)sp - 1.5f;
        pulse[i] = (erff(5.336446f * bt * (t + 0.5f)) - erff(5.336446f * bt * (t - 0.5f))) / 2;
    }
    for (int i = 0; i < nsym; ++i)
        for (int j = 0; j < 3 * sp; ++j) dphi[j + i * sp] += dphi_peak * sym[i] * pulse[j];
    for (int j = 0; j < 2 * sp; ++j) {
        dphi[j] += dphi_peak * pulse[j + sp] * sym[0];
        dphi[j + nsym * sp] += dphi_peak * pulse[j] * sym[nsym - 1];
    }
    float phi = 0;
    for (int k = 0; k < nwave; ++k) { sig[k] = sinf(phi); phi = fmodf(phi + dphi[k + sp], 2 * (float)M_PI); }
    int ramp = sp / 8;
    for (int i = 0; i < ramp; ++i) {
        float env = (1 - cosf(2 * (float)M_PI * i / (2 * ramp))) / 2;
        sig[i] *= env;
        sig[nwave - 1 - i] *= env;
    }
    free(dphi);
    free(pulse);
}

/* Gera o áudio de uma mensagem. Retorna o número de amostras escritas, ou -1 se a mensagem não puder ser codificada. */
EXPORT int ftx_encode_message(const char* text, int protocol, float freq, int sample_rate, float* out, int max_samples)
{
    ftx_message_t msg;
    if (ftx_message_encode(&msg, &hash_if, text) != FTX_MESSAGE_RC_OK) return -1;
    int ft4 = protocol != 0;
    int nn = ft4 ? FT4_NN : FT8_NN;
    uint8_t tones[FT4_NN];
    if (ft4) ft4_encode(msg.payload, tones); else ft8_encode(msg.payload, tones);
    float period = ft4 ? FT4_SYMBOL_PERIOD : FT8_SYMBOL_PERIOD;
    int n = nn * (int)(0.5f + sample_rate * period);
    if (n > max_samples) return -1;
    synth(tones, nn, freq, ft4 ? FT4_BT : FT8_BT, period, sample_rate, out);
    return n;
}
