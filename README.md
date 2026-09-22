# Frases e Pensamentos — Publicador

Este repositório mantém o publicador de Stories já existente e, em pipeline isolado, o publicador da Nova Linha Editorial no feed do Instagram.

## Stories

O fluxo de Stories permanece separado e não deve ser alterado por mudanças na Nova Linha Editorial.

## Nova Linha Editorial — fluxo oficial

**Radar → aprovação no ChatGPT → criação final no ChatGPT → envio dos arquivos finais para o GitHub → fila de publicação → Instagram.**

A criação visual final não é feita por este repositório. O GitHub não recria, não redimensiona e não reinterpreta a arte recebida.

### Ingestão

Depois que o conteúdo estiver finalizado e validado no ChatGPT:

1. os arquivos finais são gravados em `queue/novalinha/<id>/`;
2. carrosséis usam um arquivo independente por slide;
3. a legenda e os metadados são registrados em `database/novalinha_posts.json`;
4. o item entra diretamente com `status: "QUEUED"`;
5. não existe uma segunda etapa de aprovação na fila.

A especificação completa está em `docs/NOVALINHA_INGESTAO_CHATGPT.md`.

### Publicação

O workflow `.github/workflows/novalinha-publicador.yml` roda diariamente às **07:00 de Brasília** e publica no máximo **1 conteúdo por dia**.

Tipos aceitos:
- `CARROSSEL`: 2 a 7 arquivos;
- `ESTATICO`: exatamente 1 arquivo.

Estados da fila:
- `QUEUED`: pronto para publicar;
- `PUBLISHED`: publicado com sucesso;
- `ERROR`: falha de publicação, exige revisão antes de nova tentativa.

O publicador usa a Instagram Graph API. As imagens são hospedadas temporariamente no ImgBB apenas para fornecer URLs públicas à API da Meta.

### Secrets usados pelo publicador

- `INSTAGRAM_USER_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `IMGBB_API_KEY`
- `TEST_TELEGRAM_BOT_TOKEN` (opcional, para aviso)
- `TEST_TELEGRAM_CHAT_ID` (opcional, para aviso)

### Regra de segurança

Somente arquivos finais produzidos e validados no ChatGPT devem entrar na fila. Pacotes antigos do renderer, itens `READY_TO_PUBLISH` do repositório de criação e conteúdos coletados do Telegram não alimentam mais este pipeline.
