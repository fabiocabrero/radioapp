# Comparativo: IC-7300 Station × World Radio League × Ham Radio Deluxe

Fontes: worldradioleague.com e hamradiodeluxe.com (páginas iniciais, consultadas em 07/11/2026). Só entram recursos que as páginas citam.
Legenda: ✅ temos · 🟡 temos em parte · ❌ não temos · ➖ fora da proposta

## World Radio League (WRL)

| Recurso do WRL | Situação | Observação |
|---|---|---|
| Logbook na web, sincronizado entre web, desktop e celular | ❌ | O nosso log é local (ADIF); não há nuvem nem app de celular |
| Busca de indicativo ao logar | ✅ | cty.dat (país, zonas), HamQTH com a sua conta, busca no mapa |
| Importar e exportar ADIF | 🟡 | Exporta ADIF 3.1.4 e Cabrillo 3.0; **falta importar ADIF** |
| API gratuita para integrações | ➖ | Não oferecemos serviço |
| Integração com QRZ, LoTW, WSJT-X | ❌ | **Falta:** envio ao LoTW/QRZ Logbook/eQSL/Club Log e o registro automático dos QSOs do WSJT-X (UDP) |
| Painéis e métricas do log (ex.: taxa de QSOs) | ❌ | Só a contagem de DXCC e zonas nos concursos |
| Mapa dos contatos do log | 🟡 | Temos o mapa de estações ao vivo; falta plotar o **log** no mapa |
| Acompanhamento de prêmios (awards) | 🟡 | DXCC e zonas CQ nos concursos; faltam DXCC geral, WAZ, WAS, POTA hunter/activator |
| Cartão QSL automático | ❌ | |
| Log e referências de POTA | ✅ | POTA, SOTA e WWFF no log; ativações com contagem para validar (10 QSOs) |
| POTA AutoSpot (spot de si mesmo) | ❌ | Exige a API de postagem do POTA |
| SOTA | 🟡 | Só referências no log (os termos da API do SOTA exigem aprovação do projeto) |
| Filtros de spots (inclusive por classe de licença) e alertas | 🟡 | Spots do cluster/POTA/WWFF/RBN com filtros; faltam **alertas** (aviso sonoro de DX/estação desejada) e filtro por classe |
| Concursos ao vivo com pontuação em tempo real | 🟡 | Log de concurso, duplicados, Cabrillo; sem placar ao vivo |
| Calendário de concursos e eventos | ✅ | WA7BNM |
| Logs de Field Day (individual e de clube, multioperador) | ❌ | |
| Mapa de contatos em tempo real, modos extras (FT8, FT2, JTTY) | ✅ | PSK Reporter/WSPR/RBN em tempo real; FT8/FT4 |
| Desafios e jogos | ❌ | |
| Documentação, fórum, Discord | 🟡 | Guia rápido, questionário e GitHub; sem fórum |

## Ham Radio Deluxe (HRD)

| Recurso do HRD | Situação | Observação |
|---|---|---|
| Controle do rádio (CAT) de Yaesu, Icom, Kenwood, Elecraft, Ten-Tec, FlexRadio | ✅ | IC-7300 nativo e mais de 300 modelos pelo Hamlib (Elecraft, Ten-Tec e Flex incluídos); só o rádio de teste foi validado |
| Logbook com mais de 200 prêmios em 16 programas | 🟡 | Log com ADIF; prêmios só em parte (acima) |
| Envio ao LoTW, sincronização com eQSL, Club Log e QRZ | ❌ | |
| Ligação direta com o WSJT-X (FT8/FT4 no log automático) | ❌ | Só usamos o WSJT-X pelo rigctld e pelos executáveis dele |
| Log de POTA | ✅ | |
| Digital Master (RTTY, PSK31 e outros) | 🟡 | RTTY, SSTV, FT8/FT4 e CW nativos; FST4/Q65/JT/WSPR (RX) pelo WSJT-X; **PSK31, MFSK, Olivia** só pelo Fldigi |
| Rastreamento de satélites com Doppler e az/el | ✅ | Passagens, polar, Doppler e sintonia no rádio; **o az/el para rotor ainda não** |
| Controle de rotor (azimute e az/el: Yaesu, HyGain, M2) | 🟡 | **Card de direção da antena** com caminho curto e longo e botão que gira o rotor pelo `rotctld` do Hamlib (rotor ainda não testado de verdade) |
| Ferramentas: validador de log, analisador de DXCC do LoTW | ❌ | |
| Mapa e cluster | ✅ | (a página do HRD não cita; nós temos mapa, cluster e propagação) |

## O que temos e eles não citam

Mapa de calor de propagação para a frequência de operação, painel fixo com localidade e radioperador, satélites com NOAA/CelesTrak/SatNOGS,
ondas curtas (EiBi), RBN/WSPR/WWFF no mapa, plano de bandas por país com avisos de privilégio, chamadas automáticas com escuta do canal e
suspensão pelo PTT do operador, efeitos de voz (compressão, presença, eco, reverb), gravação das conversas, identificação offline do indicativo
falado, instalador com assistente que instala os programas de terceiros e gera as instruções com os seus dados.

## O que falta, em ordem sugerida

1. **Registro automático dos QSOs do WSJT-X e do JS8Call** (escutar o UDP deles): pequeno, de alto valor e dá vida ao log.
2. **Importar ADIF** e **mapa do log** (os contatos plotados).
3. **Prêmios**: DXCC geral por banda/modo, WAZ, WAS, POTA hunter/activator (só cálculo local sobre o log).
4. **Alertas de spots** (som/aviso por indicativo, país, banda ou referência POTA/WWFF).
5. **Envio ao LoTW, QRZ Logbook, eQSL e Club Log** (cada um exige a conta e a chave/certificado do operador; o LoTW exige o TQSL).
6. **Cartão QSL automático** (imagem gerada a partir do log).
7. **Placar de concurso ao vivo**, **Field Day** (log multioperador) e **az/el do rotor para satélites**.
8. Fora da proposta por ora: nuvem e app de celular (exigem servidor), fórum e jogos.
