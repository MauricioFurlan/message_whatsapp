# Comandos de Release

## Build (gera o .exe + zip versionado)

```bash
build.bat 1.2.0
```

Isso atualiza `version.py`, gera o executável e cria `dist/WhatsAppAutomacao-v1.2.0.zip`.

## Publicar no GitHub

```bash
gh release create v1.2.0 ./dist/WhatsAppAutomacao-v1.2.0.zip --title "v1.2.0" --notes-file CHANGELOG.md
```

## Teste local

```bash
python app.py --planilha test
```
