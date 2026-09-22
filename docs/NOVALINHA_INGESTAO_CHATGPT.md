# Ingestão da Nova Linha Editorial pelo ChatGPT

## Objetivo

Definir o contrato entre a criação final feita no ChatGPT e a fila operacional de publicação no GitHub.

## Fluxo

Radar → aprovação no ChatGPT → criação final no ChatGPT → envio dos arquivos finais para o GitHub → fila de publicação → Instagram.

## Destino dos arquivos

Cada conteúdo deve ser armazenado em:

`queue/novalinha/<id>/`

Exemplo de carrossel:

- `queue/novalinha/2026-09-22-pauta-01/slide_01.png`
- `queue/novalinha/2026-09-22-pauta-01/slide_02.png`
- `queue/novalinha/2026-09-22-pauta-01/slide_03.png`
- `queue/novalinha/2026-09-22-pauta-01/slide_04.png`
- `queue/novalinha/2026-09-22-pauta-01/slide_05.png`

Cada slide é um arquivo independente. Não usar prancha, grade ou montagem contendo vários slides em uma única imagem.

## Registro na fila

Após gravar os arquivos, acrescentar um item a `database/novalinha_posts.json`.

### Carrossel

```json
{
  "id": "2026-09-22-pauta-01",
  "tipo": "CARROSSEL",
  "assets": [
    "queue/novalinha/2026-09-22-pauta-01/slide_01.png",
    "queue/novalinha/2026-09-22-pauta-01/slide_02.png",
    "queue/novalinha/2026-09-22-pauta-01/slide_03.png",
    "queue/novalinha/2026-09-22-pauta-01/slide_04.png",
    "queue/novalinha/2026-09-22-pauta-01/slide_05.png"
  ],
  "caption": "Legenda final",
  "status": "QUEUED",
  "scheduled_for": "2026-09-24T07:00:00-03:00",
  "queued_at": "ISO-8601",
  "source": "chatgpt_final"
}
```

### Post estático

```json
{
  "id": "2026-09-22-post-01",
  "tipo": "ESTATICO",
  "assets": [
    "queue/novalinha/2026-09-22-post-01/post.png"
  ],
  "caption": "Legenda final",
  "status": "QUEUED",
  "queued_at": "ISO-8601",
  "source": "chatgpt_final"
}
```

## Regras

- Não usar campo `aprovado`: a aprovação já aconteceu no ChatGPT.
- Não coletar arquivos do Telegram.
- Não coletar pacotes `READY_TO_PUBLISH` do renderer antigo.
- Não adicionar item à fila antes de todos os arquivos estarem gravados.
- Não substituir silenciosamente um item já publicado.
- Se um conteúdo precisar ser corrigido antes da publicação, substituir os arquivos e metadados enquanto estiver em `QUEUED`.
- Se estiver em `ERROR`, corrigir a causa e retornar manualmente o status para `QUEUED`.
- Todo item `QUEUED` deve possuir `scheduled_for` com data, hora e fuso.
- O publicador ignora itens cuja data/hora ainda não chegou.
- Entre os itens vencidos, o publicador escolhe o de `scheduled_for` mais antigo.
- O workflow roda diariamente às 07:00 de Brasília; portanto, nesta fase, os conteúdos da Nova Linha Editorial devem ser programados para 07:00.
- O publicador impede mais de uma publicação da Nova Linha Editorial no mesmo dia.
