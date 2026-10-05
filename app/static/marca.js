// Identidade da igreja (nome, logo e cor) — carregado no <head> de cada página.
// A última configuração fica no localStorage: a marca aparece na hora, sem "piscar"
// e também offline. Depois busca /api/config e atualiza se mudou.
(function () {
  const CHAVE = 'ebd_marca';
  const PADRAO = { nome_igreja: 'Sistema EBD', nome_app: 'EBD', cor_primaria: '#4f46e5', logo_url: null, versao: 0 };
  const tituloOriginal = { v: null };
  let atual = PADRAO;

  function lerCache() {
    try { return { ...PADRAO, ...JSON.parse(localStorage.getItem(CHAVE) || '{}') }; } catch (e) { return PADRAO; }
  }
  function guardar(cfg) {
    try { localStorage.setItem(CHAVE, JSON.stringify(cfg)); } catch (e) { /* sem armazenamento: segue sem cache */ }
  }

  function misturar(hex, alvo, fracao) {  // fracao do alvo (0-255) misturada na cor
    const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    return '#' + c.map(v => Math.round(v + (alvo - v) * fracao).toString(16).padStart(2, '0')).join('');
  }

  function aplicarCor(cor) {
    const raiz = document.documentElement.style;
    if (!/^#[0-9a-f]{6}$/i.test(cor) || cor.toLowerCase() === PADRAO.cor_primaria) {
      ['--primary', '--primary-dark', '--primary-light', '--primary-muted', '--primary-rgb'].forEach(v => raiz.removeProperty(v));
      return;  // cor padrão: vale o CSS original de cada página
    }
    raiz.setProperty('--primary', cor);
    raiz.setProperty('--primary-dark', misturar(cor, 0, 0.15));
    raiz.setProperty('--primary-light', misturar(cor, 255, 0.9));
    raiz.setProperty('--primary-muted', misturar(cor, 255, 0.55));
    raiz.setProperty('--primary-rgb', [1, 3, 5].map(i => parseInt(cor.slice(i, i + 2), 16)).join(','));
  }

  function aplicarTextos(cfg) {
    document.querySelectorAll('[data-marca="nome-app"]').forEach(el => { el.textContent = cfg.nome_app; });
    document.querySelectorAll('[data-marca="nome-igreja"]').forEach(el => { el.textContent = cfg.nome_igreja; });
    document.querySelectorAll('[data-marca="logo"]').forEach(el => {
      if (!el.dataset.emoji) el.dataset.emoji = el.textContent.trim();
      el.textContent = '';
      if (cfg.logo_url) {
        const img = document.createElement('img');
        img.src = cfg.logo_url;
        img.alt = '';
        img.style.cssText = 'width:100%;height:100%;object-fit:contain;border-radius:inherit;display:block';
        el.style.background = 'transparent';
        el.appendChild(img);
      } else {
        el.style.background = '';
        el.textContent = el.dataset.emoji;
      }
    });
    if (tituloOriginal.v === null) tituloOriginal.v = document.title;
    document.title = tituloOriginal.v.replace(/— Sistema EBD$/, '— ' + cfg.nome_igreja);
  }

  function aplicarHead(cfg) {
    const v = cfg.versao ? '?v=' + cfg.versao : '';
    const tema = document.querySelector('meta[name="theme-color"]');
    if (tema) tema.content = cfg.cor_primaria;
    document.querySelectorAll('link[rel="apple-touch-icon"]').forEach(l => { l.href = '/marca/apple-touch-icon.png' + v; });
    document.querySelectorAll('link[rel="icon"]').forEach(l => { l.href = '/marca/icon-192.png' + v; });
  }

  function aplicar(cfg) {
    atual = cfg;
    window.MARCA = cfg;
    aplicarCor(cfg.cor_primaria);
    aplicarHead(cfg);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => aplicarTextos(cfg), { once: true });
    else aplicarTextos(cfg);
    document.dispatchEvent(new CustomEvent('marca:atualizada', { detail: cfg }));
  }

  // Usado pela tela de Cadastros ao salvar: guarda e aplica sem recarregar.
  window.atualizarMarca = function (cfg) { guardar(cfg); aplicar({ ...PADRAO, ...cfg }); };

  aplicar(lerCache());
  fetch('/api/config').then(r => (r.ok ? r.json() : null)).then(cfg => {
    if (!cfg) return;
    if (JSON.stringify({ ...PADRAO, ...cfg }) !== JSON.stringify(atual)) { guardar(cfg); aplicar({ ...PADRAO, ...cfg }); }
    else guardar(cfg);
  }).catch(() => { /* offline: fica com a marca guardada */ });
})();
