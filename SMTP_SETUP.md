# Configurar el correo de contacto

El formulario guarda cada consulta en `datos/contactos.jsonl` y después intenta enviarla a `info@ariki.group`. Para activar el correo:

1. Copia `smtp.ini.example` como `smtp.ini` en esta carpeta.
2. Sustituye los valores de ejemplo por el host, puerto, usuario y contraseña SMTP de tu proveedor. Usa `starttls` para el puerto 587 o `ssl` si tu proveedor requiere TLS implícito, normalmente en el puerto 465.
3. Usa como `from` una dirección autorizada por ese proveedor.
4. Reinicia `python app.py`.

No compartas la contraseña SMTP. `smtp.ini` está excluido de Git. Si SMTP no está configurado o el envío falla, la consulta se conserva localmente y el formulario lo indica; el fichero está en `datos/contactos.jsonl` y no se sirve por HTTP.
