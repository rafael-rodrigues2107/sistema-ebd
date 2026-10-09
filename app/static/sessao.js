// Sessão do Sistema EBD — carregado antes do script de cada página.

// Apaga só os dados de login. Fila de sincronização, rascunhos e cache
// offline da chamada ficam guardados para serem enviados após novo login.
const CHAVES_SESSAO = ['ebd_role', 'ebd_nome', 'ebd_turma_id'];

function limparSessao() {
  CHAVES_SESSAO.forEach(k => localStorage.removeItem(k));
}

// Sessão expirada (API respondeu 401): volta para o login.
// A espera dá tempo da página guardar localmente o que estava salvando.
(function () {
  const fetchOriginal = window.fetch.bind(window);
  let redirecionando = false;

  window.fetch = async (input, init) => {
    const resp = await fetchOriginal(input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (resp.status === 401 && url.includes('/api/') && !url.includes('/api/auth/login') && !redirecionando) {
      redirecionando = true;
      limparSessao();
      setTimeout(() => window.location.replace('/login.html?expirou=1'), 1500);
    }
    if (resp.status === 403 && url.includes('/api/') && !url.includes('/api/auth/trocar-senha') && !redirecionando) {
      // senha temporária: nada funciona até o usuário definir a própria senha
      const corpo = await resp.clone().json().catch(() => ({}));
      if (corpo.detail === 'Troca de senha obrigatória') {
        redirecionando = true;
        window.location.replace('/trocar-senha.html');
      }
    }
    return resp;
  };
})();
