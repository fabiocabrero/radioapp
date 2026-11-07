# IC-7300 Station — Guia rápido

Versão 0.2.0 (fase de testes) · Autor: Fabio Cabrero, PR2FAB · https://github.com/fabiocabrero/radioapp

## 1. Proposta

**Um app de radioamadores, para radioamadores, aberto e completo:** centraliza as informações e elimina as longas buscas em
sopas de letrinhas e a instalação e o uso de um aplicativo para cada coisa. (Texto completo em Apps > Sobre e log.)

O IC-7300 não aceita firmware de terceiros. Este app roda no PC (Windows) e usa o cabo USB do rádio (CI-V e áudio)
para reunir numa só janela o que normalmente exige vários programas: controle do rádio, espectro, modos digitais,
mapa de estações, propagação, satélites, log e concursos. A ideia é a de um "painel de apps", como o do Xiegu X6100.

O app **não substitui** WSJT-X, JS8Call, Fldigi, Winlink e afins: ele os **orquestra**. Ao clicar numa estação, sintoniza
o rádio no modo certo, copia o indicativo e abre o programa adequado.

**Estado honesto:** a recepção foi validada no IC-7300 real (conexão, frequência, modo, scope, áudio). A interface nova,
a restauração do scope ao sair e **toda a transmissão** ainda não foram testadas no rádio. Por isso este pedido de testes.

## 2. Instalação (5 minutos)

1. Execute `IC7300Station-Setup-0.2.0.exe`. O Windows (SmartScreen) vai avisar "editor desconhecido": o instalador não é
   assinado. Clique em *Mais informações > Executar assim mesmo* só se você confia na origem.
2. Na primeira abertura surge o **Assistente de primeiros passos**: indicativo, nome, cidade, grid, porta COM e áudio.
   Ele também pode instalar WSJT-X, JS8Call, Fldigi, Winlink Express e FreeDV pelo `winget` (baixa do site do autor e
   confere o hash). O Windows pedirá permissão de administrador para cada um: é normal, a decisão é sua.
3. No rádio: menu `SET > Connectors > CI-V`: **CI-V USB Port = Unlink from [REMOTE]**, **CI-V Baud Rate = 115200**,
   endereço 94h, **CI-V Transceive = ON** (se usar o app com outros programas, mantenha igual em todos).
4. Conecte o cabo USB. No Windows devem aparecer uma porta COM ("Silicon Labs CP210x") e o áudio "USB Audio CODEC".
5. No app: escolha a porta COM e o áudio na tela **Configurações** (ou deixe o assistente fazer) e marque **Conectar**.
   Sem o rádio, marque **Simulador** para conhecer as telas.

Desinstalar remove o programa e mantém suas configurações e o log em `%APPDATA%\IC7300App`.

## 2b. Outros rádios (Icom, Yaesu, Kenwood e mais)

O app é independente de marca e modelo pelo **Hamlib**. Em *Apps > Configurações > Rádio*:
1. **Tipo de rádio** = *Outro rádio: Icom, Yaesu, Kenwood e mais (via Hamlib)*.
2. Escolha a **marca** e o **modelo** (lista com mais de 300 rádios), a **porta serial** e a **velocidade** do menu do rádio (CAT).
3. Escolha o **áudio** do rádio (cada marca mostra um nome; muitos aparecem como "USB Audio CODEC").
4. **Conectar**. O app inicia o `rigctld` do Hamlib sozinho (ele vem com o WSJT-X; sem ele o app avisa).
Se outro programa já controla o rádio e oferece um `rigctld`, escolha *rigctld já em execução* e informe `host:porta`.

Diferenças: o **scope** do rádio é só do IC-7300 nativo (nos outros o espectro vem do áudio); medidores, CW pelo manipulador do rádio e níveis
dependem do que o modelo informa ao Hamlib. Frequência, modo (inclusive DATA), PTT e volume funcionam em todos os modelos que o Hamlib controla.
**Ainda não testado em rádios Yaesu, Kenwood ou outros Icom reais.**

## 2c. Sua localização e a direção da antena

- **Na primeira abertura** (e sempre que a localização ainda não foi confirmada) o app tenta obter a posição pelo Windows. **Mesmo que consiga, pede a sua
  confirmação**; se não conseguir (sem GPS ou o Windows não informa), pede **coordenadas ou o grid locator** (um preenche o outro). Também em
  *Apps > Local / GPS > Detectar e confirmar localização*. Com um GPS NMEA ligado, a primeira posição da sessão que mude mais de 1 km também pede confirmação.
- No Windows: *Configurações > Privacidade e segurança > Localização* precisa estar ligada para a detecção funcionar.
- **Card "Direção da antena"** na tela do **Rádio** (serve para fonia e digital) e na tela **FT8/FT4**: mostra o azimute em graus e o ponto cardeal para o contato
  (caminho curto e, tracejado, o longo), com a distância, num mostrador. O alvo vem da estação escolhida no mapa, do **grid do contato** ou, na falta dele,
  do centro do país do indicativo (aproximado, e o card avisa). Para girar o rotor, informe o `rotctld` do Hamlib (`host:porta`) e clique em **Girar antena**.

## 3. Funcionalidades

| Área | O que faz |
|---|---|
| Rádio | Frequência, modo, filtros, passo, S-meter, potência, ROE, volume AF, ganho RF, squelch, PTT, **PARAR TX** sempre visível |
| Espectro | Scope e waterfall do próprio rádio (CI-V 0x27), com plano de bandas |
| Mapa de estações | PSK Reporter, WSPR, Reverse Beacon, DX Cluster, POTA, WWFF e FT8 local; clique na estação e escolha como conectar |
| Painel fixo (ℹ) | Propagação agora, mapa de calor da sua frequência, localidade e tempo do contato, dados do radioperador (HamQTH) ou busca |
| Fonia e voz | Efeitos de áudio (compressão, presença, corte de graves, porta de ruído, eco, reverb) no seu microfone e no áudio recebido; gravação das conversas (manual ou automática ao detectar voz); mensagens gravadas em voz e CW; chamadas automáticas com intervalo ajustável e escuta do canal; identificação offline do indicativo pela voz (opcional) |
| Satélites | Passagens sobre o seu QTH, gráfico polar, Doppler, transmissores (CelesTrak e SatNOGS) |
| Ondas curtas | Quem está no ar agora (EiBi), com sintonia por duplo clique |
| Concursos, POTA, log | Calendário, log com duplicados, Cabrillo 3.0, ADIF, referências POTA/SOTA/WWFF |
| Plano de bandas | Brasil (classes A/B/C), EUA, Canadá, IARU R1/R2/R3; o app avisa, não impede |
| Winlink e outros | Detecta, abre e explica a ligação de VARA, VarAC, Pat, JS8Call, Fldigi, WSJT-X, FreeDV, MMSSTV, N1MM |
| Assistente | Instala programas de terceiros e gera instruções com os seus dados |
| Sobre e log | Proposta do projeto, fontes de dados, estado dos testes e o registro de eventos para anexar a relatos de problema |

Atalhos: **F1** Rádio · **F2** Apps · **Esc** volta.

## 4. Modos e recursos: o que roda onde

| Modo | Dentro do app | Precisa de programa externo? | Situação |
|---|---|---|---|
| FT8 / FT4 | Decodifica e transmite (ft8_lib) | Opcional: WSJT-X | RX validado só em simulação; **TX não testado** |
| CW | Decodificador e envio pelo manipulador do rádio, macros F1–F8 | Não | **TX não testado** |
| RTTY | Recepção e transmissão (AFSK) | Não | Validado por ida e volta; **TX não testado no ar** |
| SSTV | Martin M1/M2, Scottie S1/S2 (RX e TX) | Não | Não testado com MMSSTV/QSSTV |
| FST4, Q65, JT65, JT9, WSPR | Só recepção | Usa `jt9.exe`/`wsprd.exe` do WSJT-X | Parte validada com simuladores do WSJT-X |
| JS8 | Não | JS8Call | O app só sintoniza e abre |
| Fldigi (PSK, MFSK, Olivia...) | Não | Fldigi | O app só sintoniza e abre |
| Winlink (Pat, VARA HF/FM) | Não | Winlink Express, Pat ou VARA | VARA e VarAC são proprietários: não dá para embutir |
| Fonia (SSB/AM/FM) | Controle do rádio e ondas curtas | Não | Sintoniza em AM nas ondas curtas |
| FreeDV | Não | FreeDV | O app só abre |
| Fonia SSB/AM/FM com efeitos | Microfone do PC com efeitos, gravação, mensagens de voz e chamadas automáticas | Não | **TX não testado**; efeitos testados só com sinais sintéticos |

Limite do hardware: o IC-7300 recebe de 0,03 a 74,8 MHz. Satélites em VHF/UHF aparecem como "fora do alcance".
O mapa de calor é uma **estimativa simplificada** (SFI, Sol, absorção D-RAP, Kp), não é VOACAP.

## 5. Convivência com outros programas: o que fechar

Regra de ouro: **só um programa pode falar com o rádio por vez, e só um pode transmitir por vez.**

| Recurso | Quem disputa | Efeito se houver conflito |
|---|---|---|
| **Porta COM** (CI-V) | WSJT-X, JS8Call, Fldigi, Winlink Express, N1MM, HRD, Log4OM, DXLab, programas Icom, outro app com CAT direto | Só o primeiro abre; o outro dá "porta ocupada" ou "acesso negado" |
| **Áudio "USB Audio CODEC"** | Qualquer programa de modo digital | Dois programas decodificando é possível (no Windows costuma ser compartilhado); dois **transmitindo** misturam o áudio e saem sobrepostos |
| **PTT** | Todos os que têm PTT por CAT | TX duplo, ou PTT "preso" se um programa fechar sem soltar |
| **Relógio do PC** | FT8, FT4, WSPR, JT, Q65 | Sem sincronismo (NTP, erro > ~1 s) nada decodifica |
| **Som do Windows** | Notificações, música, vídeos | O áudio do sistema pode ir junto no TX se o dispositivo de saída padrão for o "USB Audio CODEC" |
| **CPU/rede** | Navegador com muitas abas, jogos, antivírus escaneando | Falhas na decodificação, scope travando |

### Como orientar o operador (roteiro curto)

1. **Antes de abrir o app**, feche: WSJT-X, JS8Call, Fldigi, HRD, Log4OM, DXLab, N1MM e qualquer programa da Icom (CS-7300, RS-BA1).
   No Windows: `Ctrl+Shift+Esc` > aba *Processos* > procure pelo nome > *Finalizar tarefa*.
2. **Escolha um dono do rádio.** Recomendado: o **IC-7300 Station** abre a COM e liga o **Servidor rigctl** (porta 4532).
3. **Os outros programas** usam o rádio pelo rigctl, sem tocar na COM:
   - WSJT-X, em *Settings > Radio*: Rig = `Hamlib NET rigctl`, Network Server = `127.0.0.1:4532`, PTT = `CAT`, Mode = `Data/Pkt`.
   - Em *Audio*: Entrada e Saída = `USB Audio CODEC`.
   - JS8Call e Fldigi seguem a mesma lógica (o Assistente gera as instruções com os seus dados).
   - Programas que só falam com a COM (Winlink Express com VARA, por exemplo) não funcionam junto: feche o app antes, ou feche o programa para usar o app.
4. **Um transmissor por vez.** Se o FT8 do app está em TX, o WSJT-X fica em *Monitor* (e vice-versa).
5. **Som do Windows:** em *Configurações > Sistema > Som*, deixe o dispositivo de saída padrão em alto-falantes/fones e **nunca** no USB Audio CODEC; desligue "Melhorias de áudio" no codec do rádio.
6. **Relógio:** *Configurações > Hora e idioma > Sincronizar agora* antes de usar FT8/FT4.
7. **Ao terminar:** feche os programas externos primeiro, depois o app (ele devolve o scope ao estado original, se conseguiu lê-lo).

## 5b. Fonia e voz: como usar

1. **Efeitos (TX):** *Apps > Fonia e voz > Efeitos de áudio > Meu microfone*. Para ser entendido com sinal fraco use **Compreensão DX**
   (corta graves, realça a presença, comprime). Eco e reverb prejudicam a compreensão em HF: servem para testes e conversa local.
2. **Teste sem transmitir:** escolha o microfone e os fones e aperte **TESTAR MEU ÁUDIO**. Você se ouve com os efeitos; nada vai ao rádio.
3. **Falar pelo PC:** no rádio, `MOD Input` do SSB em USB; segure **FALAR** (liga o PTT e envia o microfone com efeitos). Ajuste o ALC sem acionar.
4. **Efeitos (RX):** aba *Áudio recebido*: marque "Ouvir o áudio recebido melhorado" e escolha fones/alto-falantes do PC (nunca o USB Audio CODEC).
5. **Gravar conversas:** **GRAVAR CONVERSA** (manual) ou "Gravar automaticamente quando houver voz" (com 1,5 s antes e 4 s depois da fala). Os arquivos
   ficam em `%APPDATA%\IC7300App\gravacoes`, com a frequência e o modo no nome. Verifique as regras do seu país sobre gravar comunicações.
6. **Mensagens:** *Gravar voz* ou *Texto CW* (aceita `{call}`); *Enviar agora* transmite uma vez.
7. **Chamadas automáticas:** escolha a mensagem, o **intervalo entre chamadas** (tempo de escuta), o canal livre exigido e as repetições; **INICIAR CHAMADAS**.
   Antes de cada chamada o app escuta o canal; voz detectada adia ou encerra, conforme a opção, e interrompe a chamada em curso.
8. **PTT do operador:** se você acionar o PTT (botão do app ou microfone do rádio) fora das transmissões do app, as chamadas são **suspensas** e uma caixa
   pergunta se deve **retomar** ou encerrar. Limite: o PTT do rádio acionado *durante* uma transmissão do próprio app não é distinguível
   dela (use FALAR/PARAR TX ou a detecção de voz no microfone).
9. **Identificar indicativo pela voz (offline, opcional):** reconhece o indicativo falado em alfabeto fonético (ex.: "papa yankee dois xray xray")
   com reconhecimento local (Vosk), sem internet depois de baixar o modelo uma vez. O candidato aparece com o país (pelo prefixo no cty.dat) e a confiança;
   **confirme de ouvido**. Limites: erra com QRM, QSB forte ou fala corrida, e a validação offline confirma o prefixo, não a licença.
   O instalador já inclui o reconhecedor; o modelo de voz (cerca de 40 MB) é baixado uma vez, com a sua confirmação (rodando pelo código: `pip install vosk`).

## 6. Segurança na transmissão (leia antes de testar)

- A transmissão **nunca foi testada com rádio real**. Comece **numa carga fantasma**, potência baixa (5–10 W), ALC sem acionar.
- O botão **PARAR TX** (cabeçalho, sempre visível) solta o PTT; tenha também a mão no PTT do microfone.
- O app **avisa** quando a frequência, o modo ou a classe não permitem a transmissão, mas **a responsabilidade é do operador**.
- Senhas (Winlink, HamQTH) são suas: o app não as coloca nas instruções.

## 7. Se algo der errado

| Sintoma | Verifique |
|---|---|
| "Porta ocupada" ao conectar | Algum programa com a COM aberta (seção 5) |
| Sem espectro | *CI-V USB Port* = Unlink; baud 115200; scope ligado no rádio |
| Nada decodifica | Relógio, nível de entrada do USB (sem barras vermelhas), dispositivo de áudio certo |
| Frequência não muda no WSJT-X | Servidor rigctl marcado no app e `127.0.0.1:4532` no WSJT-X |
| Mapa vazio | Internet; PSK Reporter permite 1 consulta a cada 5 minutos |
| Instalação de terceiros falha | Veja o registro no Assistente; instale pelo site oficial do programa |

Para reportar um problema: tire um print da tela com a mensagem, anote os passos e a versão (nome do instalador, ex.: 0.2.0)
e envie junto com o questionário (`QUESTIONARIO.md`). Em **Apps > Sobre e log** está o registro de eventos do app: use *Copiar tudo*
ou *Abrir pasta do log* (`%APPDATA%\IC7300App\logs\ic7300.log`) e anexe. O log guarda versão, mensagens e erros, sem senhas.
