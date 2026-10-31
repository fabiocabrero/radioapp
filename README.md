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
- Frequências de FT8/FT4/JS8/WSPR/FT2/GhostNet (tabela do firmware X6100), sintoniza em USB + DATA
- Decodificador de CW (tom automático, WPM adaptativo) e envio de CW pelo manipulador do rádio, macros F1-F8
- DXCC (cty.dat): país, zonas, distância e azimute a partir do seu local
- Local: grid Maidenhead, lat/lon, GPS NMEA
- Log com exportação ADIF, DX Cluster (telnet) e spots POTA

## Estado e limites

- Testado com o simulador incluído e testes automáticos (`pytest`). **Ainda não foi testado com um IC-7300 real.**
  Pontos a validar no rádio: formato dos quadros do scope (0x27), comando de largura do scope e leitura DATA (0x1A 06).
- Decodificação de FT8/FT4/JS8/WSPR, Winlink/ARDOP, SSTV, NAVTEX e CW trainer ainda não estão embutidos.
