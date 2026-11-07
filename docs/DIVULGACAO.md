# Material de divulgação — pedido de apoio nos testes

Substitua [LINK] pelo endereço do instalador e [FORM] pelo link do questionário antes de enviar.

---

## Versão curta (WhatsApp / Telegram)

📻 *Voluntários para testar um app do IC-7300 (Windows)*

Sou o Fabio, PR2FAB (Itu-SP). Estou desenvolvendo, sem fins lucrativos, o **IC-7300 Station**: um app para Windows que
controla o IC-7300 pelo cabo USB e junta numa janela só: espectro, FT8/FT4, CW, RTTY, SSTV, mapa de estações ao vivo
(PSK Reporter, WSPR, RBN, POTA, WWFF), propagação com mapa de calor, satélites, ondas curtas, concursos e log.
Clicou na estação, ele sintoniza e abre a ferramenta certa.

Preciso de quem tenha IC-7300 e ~30 min para testar e contar o que funcionou e o que não funcionou.
✔ Só recepção já serve. ⚠ Teste de transmissão só em carga fantasma.
Instalador e guia: [LINK]
Questionário (5 min): [FORM]

É versão de teste: *use por sua conta e risco, o instalador não é assinado e o Windows vai avisar*. Sugestões também valem!
73, PR2FAB

---

## Versão completa (grupos, fóruns, e-mail, LABRE)

**Assunto:** Convite para testar o IC-7300 Station (app para Windows, gratuito e de código aberto)

Prezados colegas,

A proposta é simples: **um app de radioamadores, para radioamadores, aberto e completo**, que centraliza as informações e
acaba com as longas buscas em sopas de letrinhas e com a necessidade de instalar e aprender um aplicativo para cada coisa.

Sou Fabio Cabrero, PR2FAB, de Itu (SP). Desenvolvi, para uso próprio e agora aberto à comunidade, o **IC-7300 Station**:
um aplicativo para Windows que controla o Icom IC-7300 pelo cabo USB (CI-V e áudio), já que o rádio não aceita
firmware de terceiros. A proposta é reunir em um só lugar o que hoje exige vários programas.

**O que ele faz**
- Rádio: frequência, modo, filtros, S-meter, espectro e waterfall do próprio scope, volume, ganho RF e squelch
- Modos nativos: FT8/FT4, CW, RTTY e SSTV; recepção de FST4, Q65, JT65, JT9 e WSPR (com o WSJT-X)
- Mapa de estações ao vivo (PSK Reporter, WSPR, Reverse Beacon, DX Cluster, POTA, WWFF): clique no indicativo e o app
  sintoniza o rádio, copia o indicativo e abre o programa certo (WSJT-X, JS8Call, VarAC, Winlink, Pat...)
- Painel de propagação sempre visível, com mapa de calor para a sua frequência, clima e dados do radioperador
- Satélites com passagens no seu QTH, Doppler e sintonia; ondas curtas; concursos com Cabrillo; log ADIF; POTA/SOTA/WWFF
- Plano de bandas por país (Brasil, EUA, Canadá e IARU) com avisos antes de transmitir
- Instalador com assistente: pergunta seus dados e instala (com a sua autorização) WSJT-X, JS8Call, Fldigi, Winlink Express e FreeDV

**Em que estágio está**
A recepção foi validada num IC-7300 real. A interface nova, a restauração do scope ao sair do app e toda a **transmissão**
ainda não foram testadas no ar. Alguns recursos usam estimativas (o mapa de calor não é VOACAP; a órbita dos satélites tem erro de minutos).

**O que peço**
1. Instalar, conectar o rádio e usar o que lhe interessar por 30 minutos
2. Responder o questionário (5 a 10 minutos), anexando um print e o log do app (Apps > Sobre e log) se algo falhar
3. Quem puder, testar a transmissão **somente em carga fantasma, com baixa potência** e relatar

**Requisitos:** Windows 10/11, IC-7300 com cabo USB, relógio do PC sincronizado. Não é preciso instalar Python.

**Avisos honestos:** o instalador não é assinado digitalmente (o Windows SmartScreen vai alertar); o app avisa sobre
limites do plano de bandas, mas a responsabilidade da operação é sempre do operador; VARA e VarAC são proprietários e
continuam sendo programas separados.

Instalador, guia rápido e código-fonte: [LINK] · https://github.com/fabiocabrero/radioapp
Questionário: [FORM]

Obrigado e 73!
Fabio, PR2FAB

---

## Chamada para voluntários de TX (mensagem separada, para quem se oferecer)

Obrigado por se oferecer. Para o teste de transmissão, siga na ordem:
1. Carga fantasma (50 Ω), nunca antena. 2. Potência em 5–10 W. 3. Confira o ALC sem acionar.
4. Teste um modo por vez (CW, RTTY, FT8, SSTV) e verifique a potência, a modulação no analisador/outro receptor e o PTT.
5. Confirme que o **PARAR TX** solta o PTT na hora. 6. Anote o resultado no questionário (seção D).
Se algo parecer errado, desligue o rádio e me avise.

---

## Ideias de postagem (curtas, para redes e fóruns)

- "Procuro 10 PY/PU com IC-7300 para testar um app gratuito que junta FT8, CW, RTTY, SSTV, mapa ao vivo e propagação. Respondeu ao formulário, ganha meu 73 e o seu nome nos agradecimentos."
- "Um clique no indicativo e o rádio já está na frequência certa, com o programa aberto. Quero testar isso em outros rádios e PCs."
- "Esta versão é de teste e preciso do seu olhar crítico: o que falta, o que confunde, o que quebra."
