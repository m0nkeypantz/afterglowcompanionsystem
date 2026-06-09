# Browser UI

The UI is a portable Python HTTP server:

```powershell
python "$HOME\.openclaw\workspace\scripts\ui_server.py"
```

Default URL:

```text
http://127.0.0.1:8765
```

## Features

- memory table counts
- recall search
- recent diary list
- emotional gauges from `soul_state.json`
- pulse state preview

## API

```text
GET /api/summary
GET /api/tables
GET /api/diaries?limit=30
GET /api/emotion
GET /api/recall?q=<query>&limit=8
```

## Configuration

`brain/afterglow_config.json`:

```json
{
  "ui": {
    "host": "127.0.0.1",
    "port": 8765
  }
}
```

You can also override at runtime:

```powershell
python "$HOME\.openclaw\workspace\scripts\ui_server.py" --host 0.0.0.0 --port 8765
```

Only expose the UI publicly if you place it behind authentication. It can display private memories and diaries.
