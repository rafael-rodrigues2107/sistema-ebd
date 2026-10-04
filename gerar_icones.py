"""Gera os ícones PNG para o PWA sem dependências externas."""
import struct, zlib, math, os

def png(w, h, pixels):
    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b''
    for y in range(h):
        raw += b'\x00'
        for x in range(w):
            r, g, b, a = pixels[y][x]
            raw += bytes([r, g, b, a])
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    # cor RGBA — usar 6 (RGBA) em vez de 2 (RGB)
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    idat = chunk(b'IDAT', zlib.compress(raw, 9))
    iend = chunk(b'IEND', b'')
    return sig + ihdr + idat + iend

def gerar(size):
    px = [[(0,0,0,0)]*size for _ in range(size)]
    cx = size / 2
    r_outer = size / 2
    r_inner = r_outer * (1 - 96/512)  # proporção do arredondamento

    # Cores
    BG   = (79, 70, 229, 255)   # indigo-600
    WHITE = (255, 255, 255, 255)
    WHITE_T = (255, 255, 255, 230)

    def in_rounded_rect(x, y, rx=96/512):
        rr = r_outer * rx * 2
        nx, ny = x - cx, y - cx
        ax, ay = abs(nx), abs(ny)
        lim = r_outer - rr
        if ax <= lim and ay <= lim:
            return True
        if ax > r_outer or ay > r_outer:
            return False
        if ax > lim and ay > lim:
            dx, dy = ax - lim, ay - lim
            return math.sqrt(dx*dx + dy*dy) <= rr
        return ax <= r_outer and ay <= r_outer

    s = size / 512

    for y in range(size):
        for x in range(size):
            if not in_rounded_rect(x, y):
                continue
            px[y][x] = BG

            # Cruz vertical: x=[236..276], y=[100..320]
            if 236*s <= x < 276*s and 100*s <= y < 320*s:
                px[y][x] = WHITE
            # Cruz horizontal: x=[156..356], y=[168..208]
            elif 156*s <= x < 356*s and 168*s <= y < 208*s:
                px[y][x] = WHITE
            # Porta (arco): elipse centrada em 256,420, semi-eixos 40x55
            else:
                px2 = (x/s - 256)
                py2 = (y/s - 420)
                if (px2/40)**2 + (py2/55)**2 <= 1 and y/s >= 370:
                    px[y][x] = WHITE_T
                # Teto / arco da nave
                elif 140*s <= x < 372*s and 320*s <= y < 400*s:
                    # parábola: y_top = 340 - 60*((x-256)/116)^2
                    t = (x/s - 256) / 116
                    y_top = (340 - 60*t*t) * s
                    y_bot = 400 * s
                    if y_top <= y < y_bot:
                        px[y][x] = WHITE_T

    return png(size, size, px)

os.makedirs('app/static/icons', exist_ok=True)
for sz in (192, 512):
    data = gerar(sz)
    path = f'app/static/icons/icon-{sz}.png'
    with open(path, 'wb') as f:
        f.write(data)
    print(f'Gerado: {path} ({len(data)} bytes)')

print('Pronto!')
