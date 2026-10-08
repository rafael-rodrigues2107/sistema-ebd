# Roteiro: trocar nginx + certbot por Caddy (certificado automático por igreja)

> **Executado em 08/out/2026.** Certificado real emitido na primeira visita; ~14 s de parada; sem reversão.
> Este documento fica como referência (e como plano de volta enquanto o certificado antigo valer, até 19/nov/2026).

Por quê: cada igreja nova (`igreja.minhaebd.cloud`, ou domínio próprio no futuro) precisa de HTTPS. O Caddy emite o
certificado do Let's Encrypt sozinho na primeira visita e renova sozinho, mas só para domínios que o app confirma
(`GET /interno/dominio-permitido`, 200 apenas para igreja ativa). Não há mais certbot, cron nem bloco de nginx por igreja.

Validado antes, num ambiente isolado na VPS (certificados de teste): HTTPS por domínio com a marca de cada igreja,
domínio desconhecido recusado, `/interno/*` fechado para fora, HTML e `sw.js` sem cache, upload de logo de ~3,6 MB (o
nginx antigo cortava em 1 MB) e 413 acima de 6 MB. **Não** foi possível testar a emissão real do Let's Encrypt fora do
domínio de verdade: por isso a troca tem plano de volta e é feita fora do horário da EBD.

## Antes (sem derrubar nada)
1. Backup: `/usr/local/sbin/ebd-backup.sh` (confirmar `backup ok (postgres)`).
2. No `.env.prod` da VPS: `DOMINIO_BASE=minhaebd.cloud`.
3. `git pull --ff-only` e `docker compose -f docker-compose.prod.yml --env-file .env.prod build app`.
4. Guardar o compose antigo (com nginx) para voltar: `git show <commit-anterior>:docker-compose.prod.yml > /root/compose-nginx.yml`
   (o commit anterior é o da `main` antes do merge da fase 4).
5. DNS (painel da Hostinger → DNS de `minhaebd.cloud`): criar um registro **A** `*` apontando para `72.61.62.199`. Não afeta
   `dp.minhaebd.cloud` nem o apex, que têm registros próprios. (Só é necessário para as igrejas por subdomínio; a troca do
   proxy em si não depende dele.)

## Troca
1. Recriar o app (traz o endpoint de validação de domínio): `... up -d --no-deps app` (~10 s).
2. Trocar o proxy (parada de 1 a 2 minutos):
   `docker compose -f docker-compose.prod.yml --env-file .env.prod stop nginx && docker rm -f sistema-ebd-nginx-1`
   `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d caddy`
3. Primeira visita a `https://minhaebd.cloud` dispara a emissão do certificado (alguns segundos). Conferir:
   `docker logs sistema-ebd-caddy-1 2>&1 | grep -iE "obtained|error"`, `curl -I https://minhaebd.cloud/` e `https://www.minhaebd.cloud/`.
4. Conferir login, chamada e o logo (upload).

## Voltar atrás (se a emissão falhar ou algo estranho aparecer)
`docker compose -f docker-compose.prod.yml --env-file .env.prod stop caddy`, depois subir o nginx com o compose antigo:
`cd /opt/sistema-ebd && docker compose -p sistema-ebd -f /root/compose-nginx.yml --env-file .env.prod up -d nginx`.
O certificado antigo do certbot (`/etc/letsencrypt`, vale até 19/nov/2026) continua no disco para isso.

## Depois
- Desativar o certbot do host: `systemctl disable --now certbot.timer` e remover o hook
  `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx-ebd.sh` (ele recarrega um container que deixa de existir).
- **Não apagar o volume `sistema-ebd_caddy_data`**: contém os certificados e as chaves; refazer todos de uma vez bate no
  limite do Let's Encrypt. Ele entra no backup da VPS (snapshot semanal da Hostinger); considerar copiá-lo também.
- Teste com uma igreja de verdade: inserir uma igreja de teste (`insert into igrejas (nome, subdominio) values ('Teste','teste')`),
  abrir `https://teste.minhaebd.cloud`, conferir o certificado e a marca, e apagar a igreja de teste. A ferramenta do dono (fase 5)
  fará isso sem SQL.
- Atualizar o CLAUDE.md (containers: `sistema-ebd-caddy-1`; sem nginx/certbot) e o `deploy.sh`, que ainda instala nginx + certbot
  em instalações novas.

## Limites e cuidados
- O Let's Encrypt limita certificados por domínio (50 por semana) e falhas repetidas (5 por hora): o `ask` do app evita emitir
  para nomes que não são de igreja.
- O Caddy precisa das portas 80 e 443 livres na VPS (o ufw já libera). UDP 443 (HTTP/3) não é publicado.
- `/interno/*` só é seguro porque o app não é publicado na internet (só `expose`) e o Caddy responde 404 para esse caminho.
