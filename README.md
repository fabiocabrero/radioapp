# IC-7300 Station

App para Windows que controla o Icom IC-7300 pelo cabo USB (CI-V + áudio), com recursos inspirados no
firmware OpenX6100 do Xiegu X6100. O IC-7300 não aceita firmware de terceiros, por isso a solução roda no PC.

## Executar

```
pip install -r requirements.txt
python -m ic7300.main        (ou run.bat)
```

Marque **Simulador** para testar sem o rádio. Para o rádio real: no menu do IC-7300 deixe
`CI-V > CI-V USB Port = Unlink from [REMOTE]`, baud 115200 (ou o mesmo valor escolhido no app) e endereço 94h.

## Recursos

- Frequência (roda do mouse, duplo clique para digitar), modos LSB/USB/CW/CW-R/AM/FM/RTTY, DATA, filtros, passo, PTT
- Medidores S, potência e ROE
- Espectro e waterfall do scope do rádio (CI-V 0x27), com faixa do plano de bandas; fallback para espectro do áudio
- Plano de bandas (`ic7300/data/bands.json`, base IARU Região 2 — confira com a Anatel), aviso de fora de faixa,
  modo sugerido por segmento
- **FT8 e FT4**: decodificação contínua por slot, país de cada estação, sugestão de resposta (duplo clique), TX com PTT automático, botão de parada
- Frequências de FT8/FT4/JS8/WSPR/FT2/GhostNet (tabela do firmware X6100), sintoniza em USB + DATA
- Decodificador de CW (tom automático, WPM adaptativo) e envio de CW pelo manipulador do rádio, macros F1-F8
- DXCC (cty.dat): país, zonas, distância e azimute a partir do seu local
- **Mapa e propagação**: mapa-múndi offline (Natural Earth) com dia/noite, seu QTH, spots, estações FT8 decodificadas e relatos do PSK Reporter (quem te ouve / quem você ouve) com rotas; clique no mapa para distância e azimute; índices solares (SFI, A, K, manchas) e condição por banda, dia e noite, em tempo real (N0NBH/HamQSL)
- **Ondas curtas**: grade do EiBi baixada automaticamente (temporada vigente), com o que está no ar agora, horário local do PC e UTC, idioma, alvo, distância aproximada, potência e condição de propagação da faixa; filtros por banda, idioma, texto e região; duplo clique sintoniza em AM
- Local: grid Maidenhead, lat/lon, GPS NMEA
- Log com exportação ADIF, DX Cluster (telnet) e spots POTA

## Usar com WSJT-X / JS8Call / Fldigi (servidor rigctl)

Marque **Servidor rigctl** no app (porta 4532, só em 127.0.0.1) e conecte ao rádio. No WSJT-X, em
*Settings > Radio*: Rig = `Hamlib NET rigctl`, Network Server = `127.0.0.1:4532`, PTT Method = `CAT`,
Mode = `Data/Pkt`. Em *Audio*, escolha o `USB Audio CODEC`. Assim só o app abre a porta serial do rádio
e os outros programas controlam o rádio por ele. Use um único programa por vez para transmitir (o FT8 do
próprio app ou o WSJT-X), nunca os dois ao mesmo tempo.
Testado com o cliente Hamlib 4 que acompanha o WSJT-X (frequência, modo, PTT, nível S) contra o simulador.

## Estado e limites

- Testado com o simulador incluído e testes automáticos (`pytest`). **Ainda não foi testado com um IC-7300 real.**
  Pontos a validar no rádio: formato dos quadros do scope (0x27), comando de largura do scope e leitura DATA (0x1A 06).
- Ainda não embutidos: JS8, WSPR, Winlink/ARDOP, SSTV, NAVTEX e CW trainer (veja ROADMAP.md).
- FT8/FT4 decodificam e transmitem pelo app (ft8_lib, MIT). **A transmissão nunca foi testada com um rádio real**: teste primeiro numa carga fantasma, com o ALC sem acionar. O relógio do PC precisa estar sincronizado (NTP).
- `ic7300/native/ft8.dll` é gerada por `python build_native.py` (precisa de `pip install ziglang`, só para desenvolver).
