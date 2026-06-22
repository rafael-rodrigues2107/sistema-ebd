#!/bin/bash
# Script de deploy para minhaebd.cloud
# Executar no VPS: bash deploy.sh
set -e

DOMAIN="minhaebd.cloud"
REPO="https://github.com/rafael-rodrigues2107/sistema-ebd.git"
APP_DIR="/opt/sistema-ebd"

echo "=== Deploy Sistema EBD ==="

# 1. Instala Docker se necessário
if ! command -v docker &> /dev/null; then
    echo "Instalando Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# 2. Clona ou atualiza o repositório
if [ -d "$APP_DIR" ]; then
    echo "Atualizando repositório..."
    cd "$APP_DIR"
    git pull
else
    echo "Clonando repositório..."
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Cria .env de produção se não existir
if [ ! -f "$APP_DIR/.env.prod" ]; then
    echo "Criando .env.prod..."
    SECRET=$(openssl rand -hex 32)
    cat > "$APP_DIR/.env.prod" << EOF
SECRET_KEY=$SECRET
EOF
    echo "⚠️  .env.prod criado com SECRET_KEY aleatória. Guarde esse arquivo!"
fi

# 4. Sobe com config temporária (sem SSL) para o certbot validar
echo "Subindo serviços (modo HTTP)..."
cp nginx/pre-ssl.conf nginx/prod.conf
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# 5. Aguarda nginx subir
sleep 5

# 6. Emite certificado SSL
echo "Emitindo certificado SSL para $DOMAIN..."
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --email rafael.2107.rrds@gmail.com \
    --agree-tos --no-eff-email \
    -d "$DOMAIN" -d "www.$DOMAIN"

# 7. Restaura config HTTPS e reinicia nginx
echo "Ativando HTTPS..."
cp nginx/prod.conf.bak nginx/prod.conf 2>/dev/null || true
cat > nginx/prod.conf << 'NGINX'
server {
    listen 80;
    server_name minhaebd.cloud www.minhaebd.cloud;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 443 ssl;
    server_name minhaebd.cloud www.minhaebd.cloud;
    ssl_certificate     /etc/letsencrypt/live/minhaebd.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/minhaebd.cloud/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /sw.js {
        proxy_pass http://app:8000/sw.js;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }
    gzip on;
    gzip_types text/plain text/css application/javascript application/json;
}
NGINX

docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx

echo ""
echo "✅ Deploy concluído!"
echo "   Acesse: https://$DOMAIN"
echo ""
echo "Comandos úteis:"
echo "  Ver logs:    docker compose -f docker-compose.prod.yml logs -f app"
echo "  Reiniciar:   docker compose -f docker-compose.prod.yml restart app"
echo "  Atualizar:   git pull && docker compose -f docker-compose.prod.yml up -d --build app"
