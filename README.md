# IC-7300 Station

App para Windows que controla o Icom IC-7300 pelo cabo USB (CI-V + áudio), com recursos inspirados no
firmware OpenX6100 do Xiegu X6100. O IC-7300 não aceita firmware de terceiros, por isso a solução roda no PC.

## Proposta

Um app **de radioamadores, para radioamadores, aberto e completo**: centraliza as informações e elimina as longas buscas em sopas de letrinhas (VARA, ARDOP, FST4, ACDS, D-RAP...) e a instalação e o uso de um aplicativo para cada coisa. Veja também **Apps > Sobre e log** dentro do programa.

## Rádios compatíveis

- **Icom IC-7300**: CI-V nativo, com o scope do rádio (validado só em recepção).
- **Qualquer outro rádio (Icom, Yaesu, Kenwood e mais de 300 modelos)** pelo **Hamlib**: em *Apps > Configurações > Rádio* escolha
  *Outro rádio*, a marca e o modelo; o app encontra o `rigctld` (o do WSJT-X serve), lista os modelos e o inicia sozinho. Também conecta a um
  `rigctld` que já esteja rodando. Pelo Hamlib o espectro vem do áudio recebido (o scope só existe no IC-7300 nativo).
  Testado contra o `rigctld` real do Hamlib 4.6.1 com o rádio de teste (frequência, modo, DATA, PTT, volume), **não** testado com rádios Yaesu, Kenwood ou outros Icom de verdade.
  Dependem do modelo: CW pelo manipulador do rádio, medidores (S, potência, ROE) e os níveis.

## Executar

```
pip install -r requirements.txt
python -m ic7300.main        (ou run.bat)
```

Marque **Simulador** para testar sem o rádio. Para o rádio real: no menu do IC-7300 deixe
`CI-V > CI-V USB Port = Unlink from [REMOTE]`, baud 115200 (ou o mesmo valor escolhido no app) e endereço 94h.

## Recursos

- **Interface em apps**: tela principal do **Rádio** (frequência, espectro, volume, PTT) e uma tela de **Apps** em blocos, como no Xiegu; cada área (CW, FT8/FT4, RTTY, SSTV, Winlink e outros, Mapa, Ondas curtas, POTA, Concursos, Log, Configurações...) é uma tela própria. Cabeçalho fixo com frequência, modo, S-meter e o botão **PARAR TX**. Atalhos: F1 Rádio, F2 Apps, Esc volta.
- **Protocolos e modos**: catálogo com o reconhecimento de cada protocolo (categorias da IARU R2: CW, DM, ACDS, DV, imagem, IBP; códigos digitais da FCC § 97.309) e os centros de atividade oficiais da IARU para sintonizar com um clique.
- **Winlink e outros** (VARA, VarAC, Pat, ARDOP, JS8Call, Fldigi, WSJT-X, FreeDV, MMSSTV, N1MM): detecta o que está instalado, abre o programa e explica como ligá-lo ao rádio e à placa de som. VARA e VarAC são proprietários e não podem ser embutidos.
- **Plano IARU Região 2 oficial** (2020): largura máxima, modos, ACDS, balizas e centros de atividade por segmento.
- Frequência (roda do mouse, duplo clique para digitar), modos LSB/USB/CW/CW-R/AM/FM/RTTY, DATA, filtros, passo, PTT
- Medidores S, potência e ROE
- Espectro e waterfall do scope do rádio (CI-V 0x27), com faixa do plano de bandas; fallback para espectro do áudio
- **Plano de bandas por país**: Brasil (classes A/B/C, modos liberados por segmento, potência máxima por classe, balizas e repetidoras) e planos genéricos da IARU Regiões 1, 2 e 3. O plano é escolhido pelo indicativo (ou, sem indicativo, por uma caixa aproximada do país) e pode ser trocado em Local / GPS; informe sua classe para ver os privilégios e receber avisos antes de transmitir. Arquivos extras em `bandplans_custom.json` na pasta de dados do app (veja abaixo)
- **FT8 e FT4**: decodificação contínua por slot, país de cada estação, sugestão de resposta (duplo clique), TX com PTT automático, botão de parada
- Frequências de FT8/FT4/JS8/WSPR/FT2/GhostNet (tabela do firmware X6100), sintoniza em USB + DATA
- Decodificador de CW (tom automático, WPM adaptativo) e envio de CW pelo manipulador do rádio, macros F1-F8
- DXCC (cty.dat): país, zonas, distância e azimute a partir do seu local
- **Mapa e propagação**: mapa-múndi offline (Natural Earth) com dia/noite, seu QTH, spots, estações FT8 decodificadas e relatos do PSK Reporter (quem te ouve / quem você ouve) com rotas; clique no mapa para distância e azimute; índices solares (SFI, A, K, manchas) e condição por banda, dia e noite, em tempo real (N0NBH/HamQSL)
- **Mapa de estações com conexão**: camadas ao vivo de **PSK Reporter** (atividade por banda e modo, quem te ouve, quem você ouve), **WSPR** (wspr.live), **Reverse Beacon Network** (telnet, CW/RTTY), DX Cluster, POTA, **WWFF** (spots.wwff.co, sem chave) e FT8 decodificado aqui. Clique numa estação: o app mostra distância, azimute e propagação agora e oferece o que fazer conforme o modo (FT8: abrir o FT8 do app ou o WSJT-X; CW/RTTY/SSTV: a tela do modo; JS8: JS8Call; chat/Winlink: VarAC, Winlink Express ou Pat; fonia: sintonizar). A ação sintoniza o rádio no modo certo, liga o rigctl quando o programa precisa, copia o indicativo e abre o programa. Fontes que bloqueiam acesso automático (como a lista de gateways do Winlink) entram por **Importar lista (CSV/TXT)**: o app reconhece indicativo, frequência, modo e grid e aplica as mesmas ações de conexão. Também há busca por indicativo e consulta ao QRZ/HamQTH/PSK Reporter no navegador. O app não aciona a conexão dentro de programas de terceiros (VARA, VarAC, WSJT-X não têm interface de comando para isso): você cola o indicativo no campo deles.
- **Painel fixo em todas as telas** (botão ℹ Painel no cabeçalho): propagação agora (SFI, A, K, Kp do NOAA, condição na banda do rádio, alerta mais recente do NOAA SWPC) com **mapa de calor** da frequência de operação; **localidade do contato** selecionado (país, zonas CQ/ITU, grid, hora local, dia/noite, distância, azimute e tempo agora via Open-Meteo); **radioperador** (dados do HamQTH com a sua conta gratuita; sem conta, a busca por indicativo ou grid).
- **Mapa de calor no mapa**: propagação estimada para a frequência do rádio (modelo simplificado com SFI, altura do Sol, absorção D-RAP e Kp; não é VOACAP), absorção da região D (NOAA D-RAP), aurora (NOAA OVATION), nuvens e precipitação (Open-Meteo).
- **Satélites**: tela própria com as passagens sobre o seu QTH (elementos do CelesTrak, transmissores do SatNOGS DB), gráfico polar da passagem, Doppler e sintonia do rádio; marca o que o IC-7300 ouve (downlinks em HF/6 m; VHF/UHF ficam fora do alcance do rádio). Camada de satélites também no mapa. Cálculo orbital simplificado (erro de minutos).
- **Ondas curtas**: grade do EiBi baixada automaticamente (temporada vigente), com o que está no ar agora, horário local do PC e UTC, idioma, alvo, distância aproximada, potência e condição de propagação da faixa; filtros por banda, idioma, texto e região; duplo clique sintoniza em AM
- **Concursos**: calendário do WA7BNM (no ar agora e próximos 7 dias, em hora local), log de concurso com número de série automático, checagem de duplicados por banda e modo, contagem de DXCC e zonas CQ, exportação **Cabrillo 3.0** (categorias e troca variam por concurso: confira as regras)
- **POTA**: ativadores no ar com filtros por banda, modo e busca, distância e azimute, marca dos ainda não trabalhados; duplo clique sintoniza e preenche o log. O log aceita referências POTA, SOTA e WWFF (ADIF 3.1.4: POTA_REF, SOTA_REF, WWFF_REF e os MY_*), conta os QSOs da ativação (POTA valida com 10) e exporta o ADIF só da ativação
- **SOTA**: apenas referências no log. Os spots do SOTA não estão integrados: os termos da API do SOTA exigem aprovação do projeto para software de terceiros
- **RTTY** (nativo): recepção e transmissão em AFSK (45,45/50/75/100 baud, marca e shift ajustáveis, REV, UOS), validado por ida e volta com ruído
- **FST4, Q65, JT65, JT9 e WSPR** (só recepção): usa o `jt9.exe` e o `wsprd.exe` do WSJT-X instalado no PC, em slots alinhados ao relógio UTC. FST4 e Q65 foram validados com os simuladores do WSJT-X; JT65, JT9 e WSPR (marcados com *) usam o mesmo caminho, mas não foram validados com sinais reais
- **SSTV** (nativo): recepção contínua de Martin M1/M2 e Scottie S1/S2 com detecção do código VIS, correção da deriva de relógio por sincronismo de linha e imagens salvas numa galeria; transmissão de uma imagem (escolhida no PC) com legenda "CQ CQ SSTV" e seu indicativo; frequências de chamada para sintonizar com um clique. Validado por ida e volta (erro médio de 0,8 em 255 sem ruído; 300 ppm de deriva toleradas), **não** testado contra outros programas de SSTV (MMSSTV, QSSTV) nem no ar
- **Fonia e voz**: efeitos de áudio (compressão, presença, corte de graves, porta de ruído, eco, reverb) para o seu microfone (TX) e para o áudio recebido (RX), com predefinidos; teste nos fones sem transmitir; gravação das conversas (manual ou ao detectar voz); mensagens gravadas em voz e CW; chamadas automáticas com intervalo regulável, escuta do canal entre uma chamada e outra e interrupção ao detectar voz; o PTT do operador (app ou rádio) suspende as chamadas e pergunta se retoma; identificação opcional e offline do indicativo falado (Vosk, alfabeto fonético, validação pelo prefixo no cty.dat). TX nunca testado no ar
- **Localização confirmada e direção da antena**: o app detecta a posição pelo Windows (ou GPS NMEA) e **sempre pede confirmação**; sem detecção, pede coordenadas ou grid locator. O card **Direção da antena** (tela do Rádio e FT8/FT4) mostra o azimute em graus, o caminho curto e o longo e a distância ao contato para apontar antenas direcionais, e gira o rotor pelo `rotctld` do Hamlib (rotor ainda não testado de verdade)
- **Sobre e log**: proposta do projeto, fontes de dados, estado dos testes e registro de eventos (`%APPDATA%\IC7300App\logs\ic7300.log`, rotativo, sem senhas) para anexar a relatos de problema
- Local: grid Maidenhead, lat/lon, GPS NMEA
- Log com exportação ADIF, DX Cluster (telnet) e spots POTA

## Usar com WSJT-X / JS8Call / Fldigi (servidor rigctl)

Marque **Servidor rigctl** no app (porta 4532, só em 127.0.0.1) e conecte ao rádio. No WSJT-X, em
*Settings > Radio*: Rig = `Hamlib NET rigctl`, Network Server = `127.0.0.1:4532`, PTT Method = `CAT`,
Mode = `Data/Pkt`. Em *Audio*, escolha o `USB Audio CODEC`. Assim só o app abre a porta serial do rádio
e os outros programas controlam o rádio por ele. Use um único programa por vez para transmitir (o FT8 do
próprio app ou o WSJT-X), nunca os dois ao mesmo tempo.
Testado com o cliente Hamlib 4 que acompanha o WSJT-X (frequência, modo, PTT, nível S) contra o simulador.

## Plano de bandas: fontes e limites

- **Brasil**: transcrito do *Plano de Bandas BR v3.1* (PR7GA / LABRE / QTC da ECRA), que se baseia no **Ato nº 926/2024 da Anatel**
  (requisitos técnicos e operacionais). As classes e os modos por segmento foram lidos do gráfico, não de uma tabela em texto. Potências:
  Classe A 1500 W, B 1000 W, C 100 W; 60 m: 25 W EIRP. Não consegui abrir o texto oficial do Ato 926 (o site da Anatel estava em
  manutenção): **confira os limites no Ato vigente antes de transmitir**. O Ato 3448/2026 (requisitos operacionais) mantém as classes A, B e C.
- **Estados Unidos (FCC)**: gerado do texto do eCFR (47 CFR §§ 97.301, 97.303, 97.305, 97.307 e 97.313, versão de 29/10/2026), coluna da Região 2:
  privilégios por classe (Extra, Advanced, General, Technician/Novice), sub-bandas de dados e de fonia, Technician só CW em 80/40/15 m, os cinco
  canais de 60 m e as potências. Vale para os EUA contíguos, o Alasca e o Havaí; fonia em 7075-7100 kHz depende da região (nota no plano).
- **Canadá (ISED)**: gerado da Tabela I do RBR-4, Issue 3 (jul/2022): faixas, larguras máximas e qualificações (Básico, Básico com Honours ou Morse
  5 wpm, Avançado); HF exige Honours ou Avançado. O uso CW/digital/fonia dentro das faixas segue o plano IARU R2 (não é exigência legal).
- **Outros países**: ainda não incluídos (Reino Unido, Argentina, Chile, Portugal, Espanha, Uruguai, Paraguai): a Ofcom bloqueia acesso automatizado,
  o Boletín Oficial argentino não respondeu e, para os demais, não achei o texto vigente, só versões antigas, conflitantes ou bancos de perguntas de
  prova. Se você colocar o PDF da norma de um país na pasta do projeto (como fez com o driver), eu o leio e gero o plano com `tools/plan_builder.py`.
- **IARU R1/R2/R3**: genéricos (alocações da UIT por região e uso típico); não trazem classes nem potências. Para outro país, copie
  `ic7300/data/bandplans.json` para `bandplans_custom.json` na pasta de dados (`%APPDATA%\IC7300App`) e edite: planos com o mesmo id
  substituem os do app, ids novos aparecem na lista.
- O app **avisa**, não impede: fora da faixa, classe sem privilégio, modo não liberado, balizas e repetidoras. No FT8 automático, o TX
  é desabilitado se a frequência sair dos privilégios. A responsabilidade da operação é sempre do operador.

## Estado e limites

- Testado com o simulador incluído e testes automáticos (`pytest`). **Ainda não foi testado com um IC-7300 real.**
  Pontos a validar no rádio: formato dos quadros do scope (0x27), comando de largura do scope e leitura DATA (0x1A 06).
- Ainda não embutidos: JS8, WSPR, Winlink/ARDOP, SSTV, NAVTEX e CW trainer (veja ROADMAP.md).
- FT8/FT4 decodificam e transmitem pelo app (ft8_lib, MIT). **A transmissão nunca foi testada com um rádio real**: teste primeiro numa carga fantasma, com o ALC sem acionar. O relógio do PC precisa estar sincronizado (NTP).
- `ic7300/native/ft8.dll` é gerada por `python build_native.py` (precisa de `pip install ziglang`, só para desenvolver).

## Instalador para Windows

`installer/Output/IC7300Station-Setup-<versão>.exe` instala o app (Python, bibliotecas, dados e `ft8.dll` já dentro; não precisa instalar Python). Para gerar de novo: `pip install pyinstaller`, instalar o Inno Setup 6 (`winget install JRSoftware.InnoSetup`) e rodar `python installer/build.py`. O executável também aceita `--selftest <arquivo>` (abre a janela com o simulador, percorre as telas e grava OK ou o erro).

Na primeira execução abre o **Assistente de primeiros passos** (depois, em Apps > Assistente): pergunta indicativo, nome, cidade, grid e posição, a porta COM e o áudio do IC-7300; instala os programas de terceiros que você marcar e gera, para cada um (WSJT-X, JS8Call, Fldigi, Winlink Express, Pat, VARA, VarAC, FreeDV, MMSSTV, N1MM), as instruções de configuração com os seus dados (e permite salvar tudo em HTML). Nada de terceiros é redistribuído: o `winget` baixa do site do autor e confere o hash (WSJT-X, JS8Call, Fldigi, Winlink Express e FreeDV); Pat, VARA, VarAC, MMSSTV e N1MM abrem a página oficial. Senhas (Winlink, HamQTH) nunca vão para as instruções.

Ao desinstalar, as configurações e o log em `%APPDATA%\IC7300App` são mantidos.
