# Cómo colaborar

¡Gracias por querer mejorar el bot!

## Añadir rimas

Edita `defaultpuns/punsfiles/spanishpuns`. Una rima por línea:

```
disparador|rima
```

- El disparador se compara con la **última palabra** del mensaje, en minúsculas y sin tildes.
- Admite expresiones regulares: `^.*ado$|el que tengo aquí colgado`.
- Si varias rimas coinciden, el bot elige una al azar.

## Cambios en el código

1. Haz un fork y crea una rama: `git checkout -b mi-mejora`.
2. Prueba en local con tu propio bot de pruebas (crea uno en @BotFather):
   ```bash
   cp .env.example .env   # pon tu TOKEN
   ./run.sh
   ```
3. Abre un Pull Request explicando qué cambia y cómo lo has probado.

**Nunca subas tu `.env` ni tu token.** Ya están en `.gitignore`.
