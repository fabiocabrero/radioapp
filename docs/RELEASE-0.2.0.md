## IC-7300 Station 0.2.0 (versão de teste)

App para Windows que controla o Icom IC-7300 pelo USB (CI-V e áudio): espectro, FT8/FT4, CW, RTTY, SSTV, mapa de estações ao vivo, propagação com mapa de calor, satélites, ondas curtas, concursos e log.

**Estado:** recepção validada num IC-7300 real. A interface nova, a restauração do scope ao sair e toda a transmissão **não foram testadas no rádio**. Teste TX só em carga fantasma, baixa potência.

**Instalar:** baixe `IC7300Station-Setup-0.2.0.exe` abaixo. O instalador não é assinado: o Windows SmartScreen vai avisar (*Mais informações > Executar assim mesmo*). Confira o hash antes:

SHA-256: `F0D1172F30A147BA622A8DBFE9D25B970966173B0D95ABBF1CC397BE9F27E5EE`

Novidades desta versão: tela **Fonia e voz** (efeitos de áudio, gravação das conversas, mensagens de voz e CW, chamadas automáticas com escuta do canal e suspensão pelo PTT do operador), **Sobre e log** e identificação opcional de indicativo pela voz (offline). Nada disso foi testado no ar.

**Rádios:** IC-7300 nativo e, pelo Hamlib, Icom, Yaesu, Kenwood e mais de 300 modelos (testado só com o rádio de teste do Hamlib; os demais dependem de você).

Não precisa instalar Python. Guia rápido: `docs/GUIA-RAPIDO.md`. Questionário de teste: `docs/QUESTIONARIO.md`.

Requisitos: Windows 10/11, IC-7300 com cabo USB, relógio sincronizado.
