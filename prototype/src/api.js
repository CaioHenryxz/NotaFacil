// Ponte com o backend real (app/api.py, Flask local em :8000). Toda
// chamada aqui é HTTP de verdade contra o mesmo banco/regras que o app
// desktop (PySide6) usa — nada aqui é mockado.
const API_BASE = "http://127.0.0.1:8000/api";

async function req(path, options = {}) {
  const ehFormData = options.body instanceof FormData;
  let resposta;
  try {
    resposta = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: ehFormData ? options.headers : { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    // docs/auditoria.md, Bloco 7 item 1/5: o fetch() nativo do navegador
    // lança um erro em inglês ("Failed to fetch") quando o backend cai no
    // meio de uma ação -- isso vazava direto pro toast via `${e.message}`.
    // Vira uma mensagem clara em português aqui, no único lugar que todo
    // toast de erro desta ponte passa.
    throw new Error("Não deu pra falar com o programa agora. Confira se ele está aberto e tente de novo.");
  }
  let dados = {};
  try {
    dados = await resposta.json();
  } catch {
    // resposta sem corpo (ok pra alguns POST de ação)
  }
  if (!resposta.ok) {
    throw new Error(dados.erro || `Erro ${resposta.status} ao falar com o backend.`);
  }
  return dados;
}

const json = (body) => JSON.stringify(body);

export const api = {
  health: () => req("/health"),

  // --- prestadores ---
  listarPrestadores: (apenasAtivos = true) => req(`/prestadores?apenas_ativos=${apenasAtivos ? "1" : "0"}`),
  criarPrestador: (dados) => req("/prestadores", { method: "POST", body: json(dados) }),
  editarPrestador: (prestadorId, dados) =>
    req(`/prestadores/${prestadorId}/editar`, { method: "POST", body: json(dados) }),
  excluirPrestador: (prestadorId) =>
    req(`/prestadores/${prestadorId}/excluir`, { method: "POST" }),
  inativarPrestador: (prestadorId) =>
    req(`/prestadores/${prestadorId}/inativar`, { method: "POST" }),
  reativarPrestador: (prestadorId) =>
    req(`/prestadores/${prestadorId}/reativar`, { method: "POST" }),

  // --- certificado / onboarding ---
  lerCertificado: (arquivo, senha) => {
    const form = new FormData();
    form.append("arquivo", arquivo);
    form.append("senha", senha);
    return req("/certificados/ler", { method: "POST", body: form });
  },
  testarConexaoCertificado: (caminhoPfx, senha) =>
    req("/certificados/testar-conexao", { method: "POST", body: json({ caminho_pfx: caminhoPfx, senha }) }),

  buscarCnpj: (cnpj) => req(`/cnpj/${cnpj.replace(/\D/g, "")}`),

  // --- tomadores ---
  listarTomadores: (prestadorId, apenasAtivos = true) =>
    req(`/prestadores/${prestadorId}/tomadores?apenas_ativos=${apenasAtivos ? "1" : "0"}`),
  criarTomador: (prestadorId, dados) =>
    req(`/prestadores/${prestadorId}/tomadores`, { method: "POST", body: json(dados) }),
  editarTomador: (prestadorId, tomadorId, dados) =>
    req(`/prestadores/${prestadorId}/tomadores/${tomadorId}/editar`, { method: "POST", body: json(dados) }),
  excluirTomador: (prestadorId, tomadorId) =>
    req(`/prestadores/${prestadorId}/tomadores/${tomadorId}/excluir`, { method: "POST" }),
  inativarTomador: (prestadorId, tomadorId) =>
    req(`/prestadores/${prestadorId}/tomadores/${tomadorId}/inativar`, { method: "POST" }),
  reativarTomador: (prestadorId, tomadorId) =>
    req(`/prestadores/${prestadorId}/tomadores/${tomadorId}/reativar`, { method: "POST" }),

  // --- modelos de serviço ---
  listarModelos: (prestadorId) => req(`/prestadores/${prestadorId}/modelos`),
  criarModelo: (prestadorId, dados) =>
    req(`/prestadores/${prestadorId}/modelos`, { method: "POST", body: json(dados) }),
  editarModelo: (prestadorId, modeloId, dados) =>
    req(`/prestadores/${prestadorId}/modelos/${modeloId}/editar`, { method: "POST", body: json(dados) }),
  excluirModelo: (prestadorId, modeloId) =>
    req(`/prestadores/${prestadorId}/modelos/${modeloId}/excluir`, { method: "POST" }),

  // --- mensalidades (recorrências) ---
  listarRecorrencias: (prestadorId) => req(`/prestadores/${prestadorId}/recorrencias`),
  criarRecorrencia: (prestadorId, dados) =>
    req(`/prestadores/${prestadorId}/recorrencias`, { method: "POST", body: json(dados) }),
  alternarRecorrencia: (prestadorId, recorrenciaId, ativo) =>
    req(`/prestadores/${prestadorId}/recorrencias/${recorrenciaId}/alternar`, {
      method: "POST",
      body: json({ ativo }),
    }),
  editarRecorrencia: (prestadorId, recorrenciaId, dados) =>
    req(`/prestadores/${prestadorId}/recorrencias/${recorrenciaId}/editar`, { method: "POST", body: json(dados) }),
  excluirRecorrencia: (prestadorId, recorrenciaId) =>
    req(`/prestadores/${prestadorId}/recorrencias/${recorrenciaId}/excluir`, { method: "POST" }),

  // --- notas / histórico / emissão avulsa ---
  listarNotas: (prestadorId, status) =>
    req(`/prestadores/${prestadorId}/notas${status ? `?status=${status}` : ""}`),
  emitirNota: (prestadorId, dados) =>
    req(`/prestadores/${prestadorId}/notas`, { method: "POST", body: json(dados) }),
  cancelarNota: (prestadorId, notaId) =>
    req(`/prestadores/${prestadorId}/notas/${notaId}/cancelar`, { method: "POST" }),
  alertaValor: (prestadorId, tomadorId, modeloId, valor) =>
    req(`/prestadores/${prestadorId}/tomadores/${tomadorId}/alerta-valor?modelo_id=${modeloId}&valor=${encodeURIComponent(valor)}`),
  reenviarEmail: (prestadorId, notaId) =>
    req(`/prestadores/${prestadorId}/notas/${notaId}/reenviar-email`, { method: "POST" }),

  // --- meu dia / automação ---
  meuDia: () => req("/meu-dia"),
  emitirTodas: () => req("/meu-dia/emitir-todas", { method: "POST" }),
  rodarCicloAgendador: () => req("/agendador/ciclo", { method: "POST" }),

  // --- configurações ---
  obterConfig: () => req("/config"),
  salvarConfig: (dados) => req("/config", { method: "POST", body: json(dados) }),

  // --- navegador de pastas (protótipo só, backend roda na mesma máquina) ---
  listarPastas: (caminho) => req(`/pastas/listar${caminho ? `?caminho=${encodeURIComponent(caminho)}` : ""}`),
  criarPasta: (caminhoPai, nome) => req("/pastas/criar", { method: "POST", body: json({ caminho_pai: caminhoPai, nome }) }),
};
