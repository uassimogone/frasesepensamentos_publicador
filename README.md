# Frases e Pensamentos — Publicador de Stories

Automação baseada no `legaltech_publicador` para coletar uma arte do Telegram e publicá-la no Instagram Stories do perfil `@uassimogone`.

## Fluxo planejado

1. Às 04h00 (Brasília), o repositório de criação gera uma arte e envia ao bot do Telegram.
2. Às 07h30, o coletor identifica a arte mais recente, baixa `story_01.png` e monta uma fila com um item.
3. Às 08h00, o publicador hospeda temporariamente a imagem no ImgBB.
4. A Meta Graph API cria e publica um contêiner com `media_type=STORIES`.
5. A fila é marcada como publicada e o resultado é avisado no Telegram.

## Estado de segurança

Os workflows estão disponíveis apenas para execução manual. Os agendamentos estão documentados nos arquivos YAML e somente devem ser ativados depois que todos os secrets forem configurados e um teste manual publicar no perfil correto.

## Secrets necessários

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_STRING_SESSION`
- `TEST_TELEGRAM_BOT_TOKEN`
- `TEST_TELEGRAM_CHAT_ID`
- `TELEGRAM_CONTENT_CHAT_ID` (opcional; o coletor tenta derivá-lo do token do bot)
- `INSTAGRAM_USER_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `IMGBB_API_KEY`

## Requisitos da conta Meta

A conta do Instagram precisa ser profissional e estar autorizada para publicação de conteúdo pela API. Para Stories por meio do fluxo com Facebook Login, a Meta exige conta comercial vinculada a uma Página e permissão `instagram_content_publish`.
