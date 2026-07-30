# Гипертермический синдром

Открытый материал. **Читать и клонировать** может кто угодно без авторизации.
**Вносить правки** можно только по общему токену доступа (fine-grained PAT,
ограниченному только этим репозиторием).

## Просто почитать / скачать (без токена)

```bash
git clone https://github.com/metalinjector/gipertermicheskiy-sindrom.git
```

## Внести правки (нужен токен)

```bash
git clone https://<ТОКЕН>@github.com/metalinjector/gipertermicheskiy-sindrom.git
cd gipertermicheskiy-sindrom
# ...внести правки...
git add -A
git commit -m "правка: <что изменено>"
git push https://<ТОКЕН>@github.com/metalinjector/gipertermicheskiy-sindrom.git
```

Вместо `<ТОКЕН>` — строка вида `github_pat_...`, выданная в теме форума.
