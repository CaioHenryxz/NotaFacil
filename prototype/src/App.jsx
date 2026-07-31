import React, { useEffect, useState } from "react";
import {
  Sun, FileText, Users, Stethoscope, Repeat, History, Settings,
  ChevronDown, FolderOpen, Mail, MessageCircle, AlertTriangle,
  CheckCircle2, Clock, XCircle, Plus, Search, Send, ShieldCheck, Zap, X, Upload,
  Pencil, Trash2,
} from "lucide-react";
import { api } from "./api.js";

/* ------------------------------------------------------------------ */
/* Design tokens — "papel fiscal refinado" (INTOCADOS)                 */
/* ------------------------------------------------------------------ */
const T = {
  paper: "#F6F3EC",
  card: "#FFFFFF",
  ink: "#1C2522",
  inkSoft: "#5C6662",
  line: "#E4DFD3",
  green: "#0C5B43",
  greenDark: "#0A3D2E",
  greenGhost: "#E7F0EB",
  amber: "#B97A18",
  amberGhost: "#F7EDDA",
  red: "#B3402E",
  redGhost: "#F8E7E2",
  fontDisplay: "'Bricolage Grotesque', 'Georgia', serif",
  fontBody: "'Instrument Sans', 'Helvetica Neue', sans-serif",
};

const CORES_SUGERIDAS = ["#0F766E", "#C2542F", "#6D5BD0", "#0C5B43", "#B3402E", "#1D4ED8"];

const BRL = (v) => Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

/* ------------------------------------------------------------------ */
/* Atoms (INTOCADOS)                                                   */
/* ------------------------------------------------------------------ */
const Dot = ({ cor, size = 10 }) => (
  <span style={{ width: size, height: size, borderRadius: 99, background: cor, display: "inline-block", flexShrink: 0 }} />
);

const StatusPill = ({ status }) => {
  const map = {
    emitida: { bg: T.greenGhost, fg: T.green, icon: <CheckCircle2 size={13} />, label: "Emitida" },
    pendente: { bg: T.amberGhost, fg: T.amber, icon: <Clock size={13} />, label: "Na fila" },
    rejeitada: { bg: T.redGhost, fg: T.red, icon: <XCircle size={13} />, label: "Rejeitada" },
    cancelada: { bg: T.paper, fg: T.inkSoft, icon: <XCircle size={13} />, label: "Cancelada" },
  };
  const s = map[status] || map.pendente;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: s.bg, color: s.fg, padding: "4px 10px", borderRadius: 99, fontSize: 13.5, fontWeight: 600 }}>
      {s.icon}{s.label}
    </span>
  );
};

const Card = ({ children, style }) => (
  <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 14, ...style }}>{children}</div>
);

const Btn = ({ children, primary, danger, small, disabled, onClick, style, type = "button" }) => (
  <button
    type={type}
    disabled={disabled}
    onClick={onClick}
    style={{
      fontFamily: T.fontBody, cursor: disabled ? "default" : "pointer", border: "none",
      display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 600,
      borderRadius: 10, transition: "transform .08s ease, opacity .15s",
      padding: small ? "9px 15px" : "13px 22px", fontSize: small ? 14.5 : 16.5,
      opacity: disabled ? 0.55 : 1,
      background: primary ? T.green : danger ? T.red : "transparent",
      color: primary || danger ? "#fff" : T.green,
      boxShadow: primary ? "0 2px 0 #08301F" : "none",
      outline: primary ? "none" : `1.5px solid ${danger ? T.red : T.green}`,
      outlineOffset: -1.5,
      ...style,
    }}
    onMouseDown={(e) => !disabled && (e.currentTarget.style.transform = "translateY(1px)")}
    onMouseUp={(e) => (e.currentTarget.style.transform = "translateY(0)")}
  >
    {children}
  </button>
);

const Field = ({ label, children }) => (
  <label style={{ display: "block", marginBottom: 18 }}>
    <span style={{ display: "block", fontSize: 14, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase", color: T.inkSoft, marginBottom: 7 }}>{label}</span>
    {children}
  </label>
);

const inputStyle = {
  width: "100%", boxSizing: "border-box", fontFamily: T.fontBody, fontSize: 17,
  padding: "13px 15px", borderRadius: 10, border: `1.5px solid ${T.line}`,
  background: "#FCFBF7", color: T.ink, outline: "none",
};

/* Mascara de valor monetario: o usuario so' digita numeros, cada digito
   entra como centavo (docs/auditoria.md, Bloco 3, item 1 — "use mascara na
   digitacao pra eliminar ambiguidade"). Elimina na origem a ambiguidade de
   "1.500" vs "1.500,00" que antes so' quebrava depois, no backend, com um
   erro tecnico cru. */
const formatarValorMonetario = (textoDigitado) => {
  const digitos = String(textoDigitado || "").replace(/\D/g, "");
  if (!digitos) return "";
  const centavos = parseInt(digitos, 10);
  return (centavos / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

/* Validacao de digito verificador de CPF/CNPJ (docs/auditoria.md, Bloco 3,
   item 2) -- mesmo algoritmo de app/core/documentos.py, replicado aqui pra
   dar feedback na hora sem rodar ida-e-volta no backend. CNPJ alfanumerico
   (Receita Federal, producao desde 06/07/2026): usa ord(char)-48 em vez do
   digito puro nas 12 primeiras posicoes -- da o mesmo resultado de sempre
   pra CNPJ 100% numerico e ainda cobre o novo formato com letra. */
const limparDocumento = (doc) => String(doc || "").replace(/[^0-9A-Za-z]/g, "").toUpperCase();

const _digitoVerificador = (valores, pesos) => {
  const soma = valores.reduce((acc, v, i) => acc + v * pesos[i], 0);
  const resto = soma % 11;
  return resto < 2 ? 0 : 11 - resto;
};

const validarCnpj = (doc) => {
  const limpo = limparDocumento(doc);
  if (limpo.length !== 14) return false;
  const corpo = limpo.slice(0, 12);
  const dvInformado = limpo.slice(12);
  if (!/^[0-9]{2}$/.test(dvInformado) || !/^[0-9A-Z]{12}$/.test(corpo)) return false;
  const valores = [...corpo].map((c) => c.charCodeAt(0) - 48);
  const dv1 = _digitoVerificador(valores, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  const dv2 = _digitoVerificador([...valores, dv1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  return dvInformado === `${dv1}${dv2}`;
};

const validarCpf = (doc) => {
  const limpo = limparDocumento(doc);
  if (limpo.length !== 11 || !/^[0-9]{11}$/.test(limpo) || limpo === limpo[0].repeat(11)) return false;
  const digitos = [...limpo].map(Number);
  const dv1 = _digitoVerificador(digitos.slice(0, 9), [10, 9, 8, 7, 6, 5, 4, 3, 2]);
  const dv2 = _digitoVerificador([...digitos.slice(0, 9), dv1], [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]);
  return digitos[9] === dv1 && digitos[10] === dv2;
};

const validarCpfOuCnpj = (doc) => {
  const limpo = limparDocumento(doc);
  if (limpo.length === 11) return validarCpf(limpo);
  if (limpo.length === 14) return validarCnpj(limpo);
  return false;
};

const CampoValorMonetario = ({ value, onChange, style }) => (
  <input
    style={style || inputStyle}
    value={value ? `R$ ${value}` : ""}
    placeholder="R$ 0,00"
    onChange={(e) => onChange(formatarValorMonetario(e.target.value))}
  />
);

const Toggle = ({ on, onClick, disabled }) => (
  <button onClick={disabled ? undefined : onClick} style={{ width: 42, height: 24, borderRadius: 99, border: "none", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1, background: on ? T.green : T.line, position: "relative", transition: "background .15s" }}>
    <span style={{ position: "absolute", top: 3, left: on ? 21 : 3, width: 18, height: 18, borderRadius: 99, background: "#fff", transition: "left .15s", boxShadow: "0 1px 2px rgba(0,0,0,.2)" }} />
  </button>
);

const ScreenTitle = ({ kicker, title, sub, corDot }) => (
  <div style={{ marginBottom: 26 }}>
    <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: T.green, marginBottom: 6 }}>{kicker}</div>
    <h1 style={{ fontFamily: T.fontDisplay, fontSize: 37, fontWeight: 700, margin: 0, letterSpacing: "-.01em" }}>{title}</h1>
    <div style={{ color: T.inkSoft, fontSize: 16.5, marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
      {corDot && <Dot cor={corDot} />} {sub}
    </div>
  </div>
);

/* Achado real (sessão 29/jul): depois de limpar os dados de teste do banco
   (a pedido do usuário), o app ficou com ZERO prestadores cadastrados --
   e 5 telas (Emitir nota, Tomadores, Serviços, Mensalidades, Histórico)
   simplesmente retornavam `null` nesse caso, deixando a área de conteúdo
   em branco. Clicar na aba TROCAVA de tela (o React state mudava
   normalmente), só que a tela nova não mostrava nada -- parecia "clicar e
   não acontecer nada". Este componente troca o branco por uma mensagem
   acionável, igual ao aviso que já existia no seletor de prestador da
   topbar. */
const AvisoSemPrestador = ({ kicker, title }) => (
  <>
    <ScreenTitle kicker={kicker} title={title} />
    <Card style={{ padding: 28, textAlign: "center", color: T.inkSoft }}>
      <ShieldCheck size={28} style={{ marginBottom: 10 }} />
      <div style={{ fontSize: 16.5 }}>Cadastre um prestador na aba <b>"Prestadores"</b> antes de continuar.</div>
    </Card>
  </>
);

const Tag = ({ icon, txt, warn }) => (
  <span style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: 14, fontWeight: 600, padding: "5px 10px", borderRadius: 8, background: warn ? T.redGhost : T.paper, color: warn ? T.red : T.inkSoft }}>
    {icon}{txt}
  </span>
);

const IconBtn = ({ children, title, onClick, disabled }) => (
  <button title={title} disabled={disabled} onClick={onClick} style={{ border: "none", background: "transparent", color: disabled ? "#C7CBC7" : T.inkSoft, cursor: disabled ? "default" : "pointer", padding: 6, borderRadius: 8 }}
    onMouseEnter={(e) => !disabled && (e.currentTarget.style.color = T.green)}
    onMouseLeave={(e) => !disabled && (e.currentTarget.style.color = T.inkSoft)}>{children}</button>
);
const td = { padding: "14px 18px", borderBottom: `1px solid #F0EDE4` };

/* Modal genérico — novo átomo, mesmo sistema visual (sem lib nova) */
const Modal = ({ title, onClose, children, width = 560 }) => (
  <div style={{ position: "fixed", inset: 0, background: "rgba(20,30,25,.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200, padding: 20 }} onClick={onClose}>
    <div style={{ background: T.card, borderRadius: 16, padding: 28, width, maxWidth: "94vw", maxHeight: "88vh", overflowY: "auto", boxShadow: "0 24px 60px rgba(10,20,15,.3)" }} onClick={(e) => e.stopPropagation()}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <div style={{ fontFamily: T.fontDisplay, fontSize: 21.5, fontWeight: 700 }}>{title}</div>
        <button onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer", color: T.inkSoft, padding: 4 }}><X size={20} /></button>
      </div>
      {children}
    </div>
  </div>
);

/* Código de tributação nacional (cTribNac), item 4 da LC 116/2003 "Serviços
   de saúde" — docs/auditoria.md, Bloco 2.2: o campo era texto livre sem
   nenhuma sugestão, e um erro de digitação só aparecia na rejeição da
   Receita. Lista "Códigos de Tributação Nacional NFS-e" vigente a contar de
   24/11/2025 (fonte secundária reproduzindo a tabela oficial do Comitê
   Gestor; confere com o único código já confirmado por 2 fontes de mercado
   na auditoria original, 040101 = Medicina). Curada pro público deste app
   (médicos PJ e clínicas correlatas); o campo continua aceitando digitação
   livre pra qualquer código fora desta lista. */
const CODIGOS_TRIBUTACAO_NACIONAL_SAUDE = [
  ["040101", "Medicina"],
  ["040102", "Biomedicina"],
  ["040201", "Análises clínicas e congêneres"],
  ["040202", "Patologia e congêneres"],
  ["040203", "Eletricidade médica (eletroestimulação, cardioversão etc.)"],
  ["040204", "Radioterapia, quimioterapia e congêneres"],
  ["040205", "Ultrassonografia, ressonância, radiologia, tomografia"],
  ["040301", "Hospitais e congêneres"],
  ["040302", "Laboratórios e congêneres"],
  ["040303", "Clínicas, prontos-socorros, ambulatórios e congêneres"],
  ["040401", "Instrumentação cirúrgica"],
  ["040501", "Acupuntura"],
  ["040601", "Enfermagem, inclusive serviços auxiliares"],
  ["040701", "Serviços farmacêuticos"],
  ["040801", "Terapia ocupacional"],
  ["040802", "Fisioterapia"],
  ["040803", "Fonoaudiologia"],
  ["040901", "Terapias de qualquer espécie (físico, orgânico, mental)"],
  ["041001", "Nutrição"],
  ["041101", "Obstetrícia"],
  ["041201", "Odontologia"],
  ["041301", "Ortóptica"],
  ["041401", "Próteses sob encomenda"],
  ["041501", "Psicanálise"],
  ["041601", "Psicologia"],
  ["041801", "Inseminação artificial, fertilização in vitro"],
  ["041901", "Bancos de sangue, leite, pele, olhos, óvulos, sêmen"],
  ["042001", "Coleta de sangue, leite, tecidos, sêmen, órgãos"],
  ["042101", "Unidade de atendimento/assistência/tratamento móvel"],
  ["042201", "Planos de medicina de grupo/convênios de assistência"],
  ["042301", "Outros planos de saúde (terceiros credenciados/cooperados)"],
];

/* Retenções na fonte (docs/auditoria.md, Bloco 1.6/2.4) — linguagem leiga,
   sem nome de campo do XML. Reaproveitado no cadastro do tomador (padrão) e
   na emissão avulsa (sobrescrever só naquela nota). */
const RETENCOES_TRIBUTOS = [
  { retem: "retem_irrf", aliquota: "aliquota_irrf", label: "IRRF (Imposto de Renda)" },
  { retem: "retem_pis", aliquota: "aliquota_pis", label: "PIS" },
  { retem: "retem_cofins", aliquota: "aliquota_cofins", label: "COFINS" },
  { retem: "retem_csll", aliquota: "aliquota_csll", label: "CSLL" },
  { retem: "retem_inss", aliquota: "aliquota_inss", label: "INSS / contribuição previdenciária" },
];

const RETENCOES_VAZIAS = {
  retem_irrf: false, aliquota_irrf: "", retem_pis: false, aliquota_pis: "",
  retem_cofins: false, aliquota_cofins: "", retem_csll: false, aliquota_csll: "",
  retem_inss: false, aliquota_inss: "", retem_iss: false,
};

const retencoesDe = (origem) => ({
  retem_irrf: !!origem?.retem_irrf, aliquota_irrf: origem?.aliquota_irrf || "",
  retem_pis: !!origem?.retem_pis, aliquota_pis: origem?.aliquota_pis || "",
  retem_cofins: !!origem?.retem_cofins, aliquota_cofins: origem?.aliquota_cofins || "",
  retem_csll: !!origem?.retem_csll, aliquota_csll: origem?.aliquota_csll || "",
  retem_inss: !!origem?.retem_inss, aliquota_inss: origem?.aliquota_inss || "",
  retem_iss: !!origem?.retem_iss,
});

function CamposRetencao({ valores, onChange }) {
  const set = (campo, valor) => onChange({ ...valores, [campo]: valor });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      {RETENCOES_TRIBUTOS.map(({ retem, aliquota, label }) => (
        <div key={retem} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input type="checkbox" checked={valores[retem]} onChange={(e) => set(retem, e.target.checked)} style={{ width: 17, height: 17, flexShrink: 0 }} />
          <span style={{ flex: 1, fontSize: 14.5 }}>{label}</span>
          {valores[retem] && (
            <input
              style={{ ...inputStyle, width: 92, padding: "8px 10px", fontSize: 14.5 }}
              placeholder="% na nota" value={valores[aliquota]}
              onChange={(e) => set(aliquota, e.target.value)}
            />
          )}
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2, paddingTop: 9, borderTop: `1px solid ${T.line}` }}>
        <input type="checkbox" checked={valores.retem_iss} onChange={(e) => set("retem_iss", e.target.checked)} style={{ width: 17, height: 17, flexShrink: 0 }} />
        <span style={{ fontSize: 14.5 }}>ISS (usa a alíquota já cadastrada no serviço, não precisa digitar de novo)</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Meu Dia                                                       */
/* ------------------------------------------------------------------ */
function MeuDia({ setToast }) {
  const [dados, setDados] = useState(null);
  const [emitindo, setEmitindo] = useState(false);

  const carregar = () => {
    api.meuDia().then(setDados).catch((e) => setToast(`Erro ao carregar: ${e.message}`));
  };
  useEffect(carregar, []);

  if (!dados) return <ScreenTitle kicker="Carregando…" title="Meu Dia" sub="Buscando dados reais do backend…" />;

  const totalHoje = dados.mensalidades_hoje.reduce((s, m) => s + Number(m.valor), 0);
  const pendentesDeHoje = dados.mensalidades_hoje.filter((m) => !m.ja_emitida_no_mes);

  const emitirTodas = async () => {
    setEmitindo(true);
    try {
      const r = await api.emitirTodas();
      setToast(r.criadas === 0 ? "Nenhuma mensalidade pendente pra hoje" : `✓ ${r.emitidas} nota(s) emitidas e enviadas por e-mail`);
      carregar();
    } catch (e) {
      setToast(`Erro: ${e.message}`);
    } finally {
      setEmitindo(false);
    }
  };

  return (
    <>
      <ScreenTitle
        kicker={new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })}
        title="Bom dia"
        sub="Dados reais do backend — tudo aqui já é o banco de verdade."
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 14, marginBottom: 24 }}>
        <Stat icon={<Zap size={17} />} n={pendentesDeHoje.length} label="prontas pra hoje" cor={T.green} />
        <Stat icon={<Clock size={17} />} n={dados.notas_pendentes.length} label="na fila (reenvio auto)" cor={T.amber} />
        <Stat icon={<XCircle size={17} />} n={dados.notas_rejeitadas.length} label="rejeitada — ver motivo" cor={T.red} />
        <Stat icon={<ShieldCheck size={17} />} n={dados.certificados_a_vencer.length} label="certificado(s) vencendo" cor={T.red} />
      </div>

      <Card style={{ overflow: "hidden", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 22px", borderBottom: `1px solid ${T.line}` }}>
          <div>
            <div style={{ fontFamily: T.fontDisplay, fontSize: 20.5, fontWeight: 600 }}>Mensalidades de hoje</div>
            <div style={{ color: T.inkSoft, fontSize: 15, marginTop: 2 }}>{dados.mensalidades_hoje.length} notas · {BRL(totalHoje)}</div>
          </div>
          <Btn primary disabled={emitindo || pendentesDeHoje.length === 0} onClick={emitirTodas}>
            <Send size={16} /> {emitindo ? "Emitindo…" : `Emitir todas (${pendentesDeHoje.length})`}
          </Btn>
        </div>
        {dados.mensalidades_hoje.length === 0 && (
          <div style={{ padding: 22, color: T.inkSoft, fontSize: 15.5 }}>Nenhuma mensalidade cadastrada pra hoje.</div>
        )}
        {dados.mensalidades_hoje.map((m) => (
          <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "15px 22px", borderBottom: `1px solid ${T.line}` }}>
            <Dot cor={m.prestador_cor} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 16.5 }}>{m.tomador_nome}</div>
              <div style={{ color: T.inkSoft, fontSize: 14.5 }}>{m.prestador_nome} · {m.modelo_descricao}</div>
            </div>
            <div style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{BRL(m.valor)}</div>
            {m.ja_emitida_no_mes ? <StatusPill status="emitida" /> : (
              <span style={{ fontSize: 14, color: T.inkSoft, background: T.paper, padding: "4px 10px", borderRadius: 99 }}>agendada</span>
            )}
          </div>
        ))}
      </Card>

      {dados.certificados_a_vencer.length > 0 && (
        <Card style={{ padding: "13px 22px", fontSize: 14.5, color: T.inkSoft, display: "flex", gap: 8, alignItems: "center" }}>
          <AlertTriangle size={14} color={T.amber} />
          {dados.certificados_a_vencer.map((c) => `O certificado de ${c.prestador_nome} vence em ${c.dias_restantes} dia(s)`).join(" · ")}
        </Card>
      )}
    </>
  );
}

const Stat = ({ icon, n, label, cor }) => (
  <Card style={{ padding: "16px 18px" }}>
    <div style={{ color: cor, marginBottom: 8 }}>{icon}</div>
    <div style={{ fontFamily: T.fontDisplay, fontSize: 30, fontWeight: 700, lineHeight: 1 }}>{n}</div>
    <div style={{ color: T.inkSoft, fontSize: 14, marginTop: 4 }}>{label}</div>
  </Card>
);

/* ------------------------------------------------------------------ */
/* Tela: Emitir nota                                                   */
/* ------------------------------------------------------------------ */
function EmitirNota({ prestador, setToast }) {
  const [tomadores, setTomadores] = useState([]);
  const [modelos, setModelos] = useState([]);
  const [tomadorId, setTomadorId] = useState("");
  const [modeloId, setModeloId] = useState("");
  const [valor, setValor] = useState("");
  const [emitindo, setEmitindo] = useState(false);
  const [retencoes, setRetencoes] = useState(RETENCOES_VAZIAS);
  const [mostrarRetencoes, setMostrarRetencoes] = useState(false);

  useEffect(() => {
    if (!prestador) return;
    api.listarTomadores(prestador.id).then(setTomadores);
    api.listarModelos(prestador.id).then(setModelos);
    setTomadorId(""); setModeloId(""); setValor("");
  }, [prestador?.id]);

  const escolherTomador = (id) => {
    setTomadorId(id);
    // padrao do tomador (docs/auditoria.md Bloco 1.6/2.4: "a regra costuma
    // ser fixa por convenio") -- pode ser ajustado so' pra esta nota, abaixo
    const t = tomadores.find((x) => String(x.id) === String(id));
    setRetencoes(retencoesDe(t));
    setMostrarRetencoes(false);
  };

  const escolherModelo = (id) => {
    setModeloId(id);
    const m = modelos.find((x) => String(x.id) === String(id));
    if (m) setValor(formatarValorMonetario(m.valor_padrao));
  };

  const tomadorSelecionado = tomadores.find((t) => String(t.id) === String(tomadorId));
  const retemAlgumaCoisa = Object.entries(retencoes).some(([k, v]) => k.startsWith("retem_") && v);

  const emitir = async () => {
    if (!tomadorId || !modeloId || !valor) { setToast("Escolha o tomador, o serviço e confirme o valor."); return; }
    setEmitindo(true);
    try {
      const nota = await api.emitirNota(prestador.id, { tomador_id: Number(tomadorId), modelo_id: Number(modeloId), valor, retencoes });
      if (nota.status === "emitida") setToast(`✓ Nota emitida — chave ${nota.chave_acesso}. PDF salvo na pasta do prestador.`);
      else if (nota.status === "rejeitada") setToast(`✗ Rejeitada: ${nota.motivo_rejeicao_traduzido || nota.motivo_rejeicao}`);
      else setToast("Nota entrou na fila — o backend tenta de novo sozinho em instantes.");
    } catch (e) {
      setToast(`Erro: ${e.message}`);
    } finally {
      setEmitindo(false);
    }
  };

  if (!prestador) return <AvisoSemPrestador kicker="Emissão avulsa" title="Emitir nota" />;

  return (
    <>
      <ScreenTitle kicker="Emissão avulsa" title="Emitir nota" sub={`Emitindo como ${prestador.nome_exibicao}`} corDot={prestador.cor} />
      <div className="ntf-emitir-grid" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 20 }}>
        <Card style={{ padding: 26 }}>
          <Field label="Tomador (quem recebe a nota)">
            <select style={inputStyle} value={tomadorId} onChange={(e) => escolherTomador(e.target.value)}>
              <option value="">Escolher…</option>
              {tomadores.map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
            </select>
          </Field>
          <Field label="Serviço">
            <select style={inputStyle} value={modeloId} onChange={(e) => escolherModelo(e.target.value)}>
              <option value="">Escolher…</option>
              {modelos.map((m) => <option key={m.id} value={m.id}>{m.descricao}</option>)}
            </select>
          </Field>
          <Field label="Valor (R$)">
            <CampoValorMonetario
              style={{ ...inputStyle, fontSize: 23.5, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}
              value={valor} onChange={setValor}
            />
          </Field>

          {tomadorId && (
            <Field label="Retenção na fonte">
              {!mostrarRetencoes ? (
                <button onClick={() => setMostrarRetencoes(true)} style={{ border: "none", background: T.paper, borderRadius: 10, padding: "10px 14px", color: T.inkSoft, fontSize: 14, cursor: "pointer", width: "100%", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}>
                  <ShieldCheck size={15} style={{ flexShrink: 0 }} />
                  {retemAlgumaCoisa
                    ? "Esta nota vai sair com retenção (padrão do tomador) — clique pra ajustar só nesta nota"
                    : "Esta nota vai sair sem nenhuma retenção — clique pra ajustar só nesta nota"}
                </button>
              ) : (
                <CamposRetencao valores={retencoes} onChange={setRetencoes} />
              )}
            </Field>
          )}

          <Btn primary disabled={emitindo} style={{ width: "100%", justifyContent: "center", padding: "15px" }} onClick={emitir}>
            <Send size={17} /> {emitindo ? "Emitindo…" : "Emitir agora"}
          </Btn>
          {tomadores.length === 0 && <p style={{ fontSize: 14.5, color: T.inkSoft, marginTop: 10 }}>Este prestador ainda não tem tomador cadastrado.</p>}
          {modelos.length === 0 && <p style={{ fontSize: 14.5, color: T.inkSoft, marginTop: 4 }}>Este prestador ainda não tem modelo de serviço cadastrado.</p>}
        </Card>
        <Card style={{ padding: 24, background: "#FCFBF6" }}>
          <div style={{ fontFamily: T.fontDisplay, fontSize: 17.5, fontWeight: 600, marginBottom: 14 }}>O que acontece ao emitir</div>
          {["Nota assinada com o certificado do prestador — aqui no seu computador", "Enviada pro Emissor Nacional (modo teste)", "PDF e XML salvos na pasta do prestador", "E-mail automático pro tomador"].map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 10, marginBottom: 12, fontSize: 15, color: T.inkSoft }}>
              <span style={{ fontFamily: T.fontDisplay, fontWeight: 700, color: T.green }}>{i + 1}</span>{s}
            </div>
          ))}
          <div style={{ marginTop: 8, padding: 12, background: T.greenGhost, borderRadius: 10, fontSize: 14, color: T.green, display: "flex", gap: 8 }}>
            <ShieldCheck size={15} style={{ flexShrink: 0 }} /> O certificado nunca sai desta máquina.
          </div>
        </Card>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Prestadores                                                   */
/* ------------------------------------------------------------------ */
function Prestadores({ prestadores: prestadoresAtivos, recarregarPrestadores, setToast }) {
  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState(null);
  const [mostrarInativos, setMostrarInativos] = useState(false);
  const [prestadoresComInativos, setPrestadoresComInativos] = useState(null);

  const recarregarLista = () => {
    recarregarPrestadores();
    if (mostrarInativos) api.listarPrestadores(false).then(setPrestadoresComInativos);
  };
  useEffect(recarregarLista, [mostrarInativos]);
  const prestadores = mostrarInativos && prestadoresComInativos ? prestadoresComInativos : prestadoresAtivos;

  const excluir = async (p) => {
    if (!window.confirm(`Excluir o prestador "${p.nome_exibicao}"? Essa ação não pode ser desfeita.`)) return;
    try {
      await api.excluirPrestador(p.id);
      setToast("✓ Prestador excluído");
      recarregarLista();
    } catch (e) {
      // Tem nota emitida -- exclusao definitiva bloqueada de proposito
      // (docs/auditoria.md, Bloco 4.1). Oferece inativar em vez de so'
      // mostrar o erro e travar o usuario.
      if (window.confirm(
        `${e.message}\n\nDeseja inativar este prestador em vez de excluir? Ele some da lista ativa, `
        + `mas o histórico e os arquivos continuam intactos, e dá pra reativar depois (marque "Mostrar inativos").`
      )) {
        try {
          await api.inativarPrestador(p.id);
          setToast("✓ Prestador inativado");
          recarregarLista();
        } catch (e2) {
          setToast(`Não deu pra inativar: ${e2.message}`);
        }
      }
    }
  };

  const reativar = async (p) => {
    try {
      await api.reativarPrestador(p.id);
      setToast("✓ Prestador reativado");
      recarregarLista();
    } catch (e) {
      setToast(`Não deu pra reativar: ${e.message}`);
    }
  };

  return (
    <>
      <ScreenTitle kicker="Espaços isolados" title="Prestadores"
        sub="Cada prestador tem certificado, tomadores e pasta próprios — nada se mistura." />
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14.5, color: T.inkSoft, marginBottom: 12, cursor: "pointer" }}>
        <input type="checkbox" checked={mostrarInativos} onChange={(e) => setMostrarInativos(e.target.checked)} /> Mostrar inativos
      </label>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
        {prestadores.map((p) => (
          <Card key={p.id} style={{ padding: 22, borderTop: `4px solid ${p.cor || T.line}`, opacity: p.ativo === 0 ? 0.55 : 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontFamily: T.fontDisplay, fontSize: 20.5, fontWeight: 600 }}>
                  {p.nome_exibicao} {p.ativo === 0 && <span style={{ fontWeight: 400, color: T.inkSoft, fontSize: 15 }}>(inativo)</span>}
                </div>
                <div style={{ color: T.inkSoft, fontSize: 15 }}>CNPJ/CPF {p.cnpj}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                <Dot cor={p.cor} size={14} />
                {p.ativo === 0 ? (
                  <Btn small onClick={() => reativar(p)}>Reativar</Btn>
                ) : (
                  <>
                    <IconBtn title="Editar prestador" onClick={() => setEditando(p)}><Pencil size={15} /></IconBtn>
                    <IconBtn title="Excluir prestador" onClick={() => excluir(p)}><Trash2 size={15} /></IconBtn>
                  </>
                )}
              </div>
            </div>
            <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Tag icon={<ShieldCheck size={13} />} txt={`Certificado até ${p.cert_venc_em || "—"}`} />
              <Tag icon={<FolderOpen size={13} />} txt={`Notas Fiscais\\${(p.nome_exibicao || "").split(" ")[0]}…`} />
            </div>
            <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
              <Btn small onClick={() => setToast(`Pasta: Notas Fiscais\\${p.nome_exibicao}\\ (abrir pasta só funciona no app desktop)`)}>
                <FolderOpen size={14} /> Ver caminho da pasta
              </Btn>
            </div>
          </Card>
        ))}
        <button onClick={() => setModalAberto(true)} style={{ border: `2px dashed ${T.line}`, borderRadius: 14, background: "transparent", cursor: "pointer", minHeight: 170, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, color: T.inkSoft, fontFamily: T.fontBody, fontSize: 16.5 }}>
          <Plus size={22} color={T.green} /> Adicionar prestador
          <span style={{ fontSize: 14 }}>importe o certificado .pfx e pronto</span>
        </button>
      </div>
      {modalAberto && (
        <NovoPrestadorModal
          onClose={() => setModalAberto(false)}
          onCriado={() => { setModalAberto(false); recarregarLista(); setToast("✓ Prestador cadastrado"); }}
          setToast={setToast}
        />
      )}
      {editando && (
        <EditarPrestadorModal
          prestador={editando}
          onClose={() => setEditando(null)}
          onEditado={() => { setEditando(null); recarregarLista(); setToast("✓ Prestador atualizado"); }}
          setToast={setToast}
        />
      )}
    </>
  );
}

function EditarPrestadorModal({ prestador, onClose, onEditado, setToast }) {
  const [nomeExibicao, setNomeExibicao] = useState(prestador.nome_exibicao || "");
  const [im, setIm] = useState(prestador.im || "");
  const [codigoMunicipio, setCodigoMunicipio] = useState(prestador.codigo_municipio || "");
  const [regime, setRegime] = useState(prestador.regime || "3");
  const [regimeEspecial, setRegimeEspecial] = useState(prestador.regime_especial_tributacao || "0");
  const [cor, setCor] = useState(prestador.cor || CORES_SUGERIDAS[0]);
  const [salvando, setSalvando] = useState(false);

  const salvar = async () => {
    if (!nomeExibicao || !im || !codigoMunicipio) { setToast("Preencha nome, inscrição municipal e código do município."); return; }
    // TSInscMun (tiposSimples_v1.01.xsd): 1 a 15 caracteres -- unico limite
    // confirmavel contra o leiaute nacional (cada prefeitura define seu
    // proprio formato de IM, entao nao da pra travar mais que isso).
    if (im.length > 15) { setToast("A inscrição municipal tem no máximo 15 caracteres (padrão do leiaute nacional)."); return; }
    setSalvando(true);
    try {
      await api.editarPrestador(prestador.id, {
        nome_exibicao: nomeExibicao, im, codigo_municipio: codigoMunicipio,
        regime, regime_especial_tributacao: regimeEspecial, cor,
      });
      onEditado();
    } catch (e) {
      setToast(`Não deu pra salvar: ${e.message}`);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal title="Editar prestador" onClose={onClose} width={520}>
      <Field label="CNPJ/CPF (não muda)"><input style={inputStyle} value={prestador.cnpj} readOnly disabled /></Field>
      <Field label="Nome de exibição"><input style={inputStyle} value={nomeExibicao} onChange={(e) => setNomeExibicao(e.target.value)} /></Field>
      <Field label="Inscrição municipal"><input style={inputStyle} value={im} onChange={(e) => setIm(e.target.value)} /></Field>
      <Field label="Município (código IBGE)"><input style={inputStyle} value={codigoMunicipio} onChange={(e) => setCodigoMunicipio(e.target.value)} /></Field>
      <Field label="Regime (Simples Nacional)">
        <select style={inputStyle} value={regime} onChange={(e) => setRegime(e.target.value)}>
          <option value="1">Não optante pelo Simples Nacional</option>
          <option value="2">Optante — MEI</option>
          <option value="3">Optante — ME ou EPP (Simples Nacional)</option>
        </select>
        <p style={{ color: T.inkSoft, fontSize: 13.5, margin: "7px 0 0" }}>
          Se for optante (MEI ou ME/EPP), o ISS já vai embutido na guia mensal do Simples (DAS) — o campo de
          alíquota nos serviços desse prestador fica travado automaticamente, sem precisar mexer em mais nada aqui.
        </p>
      </Field>
      <Field label="Regime especial de tributação">
        <select style={inputStyle} value={regimeEspecial} onChange={(e) => setRegimeEspecial(e.target.value)}>
          <option value="0">Nenhum</option>
          <option value="1">Cooperativa</option>
          <option value="2">Estimativa</option>
          <option value="3">Microempresa Municipal</option>
          <option value="4">Notário ou Registrador</option>
          <option value="5">Profissional Autônomo</option>
          <option value="6">Sociedade de Profissionais</option>
        </select>
      </Field>
      <Field label="Cor deste prestador">
        <div style={{ display: "flex", gap: 8 }}>
          {CORES_SUGERIDAS.map((c) => (
            <button key={c} onClick={() => setCor(c)} style={{ width: 28, height: 28, borderRadius: 99, background: c, border: cor === c ? `2.5px solid ${T.ink}` : "2.5px solid transparent", cursor: "pointer" }} />
          ))}
        </div>
      </Field>
      <Btn primary disabled={salvando} style={{ width: "100%", justifyContent: "center" }} onClick={salvar}>{salvando ? "Salvando…" : "Salvar alterações"}</Btn>
    </Modal>
  );
}

function NovoPrestadorModal({ onClose, onCriado, setToast }) {
  const [passo, setPasso] = useState(1);
  const [arquivo, setArquivo] = useState(null);
  const [senha, setSenha] = useState("");
  const [senhaConfirmada, setSenhaConfirmada] = useState(null);
  const [lendo, setLendo] = useState(false);
  const [infoCert, setInfoCert] = useState(null);

  const [nomeExibicao, setNomeExibicao] = useState("");
  const [im, setIm] = useState("");
  const [codigoMunicipio, setCodigoMunicipio] = useState("");
  const [regime, setRegime] = useState("3");
  const [regimeEspecial, setRegimeEspecial] = useState("0");
  const [cor, setCor] = useState(CORES_SUGERIDAS[0]);
  const [testando, setTestando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [buscandoCnpj, setBuscandoCnpj] = useState(false);

  const lerCertificado = async () => {
    if (!arquivo || !senha) { setToast("Escolha o arquivo .pfx e digite a senha."); return; }
    setLendo(true);
    try {
      const info = await api.lerCertificado(arquivo, senha);
      setInfoCert(info);
      setSenhaConfirmada(senha); // trava a senha que REALMENTE abriu o certificado —
                                 // editar o campo depois não pode mudar o que vai ser salvo
      if (!nomeExibicao) setNomeExibicao(info.nome_titular?.split(":")[0] || "");
      setPasso(2);
    } catch (e) {
      setToast(`Certificado não pôde ser lido: ${e.message}`);
    } finally {
      setLendo(false);
    }
  };

  const trocarCertificado = () => {
    setInfoCert(null);
    setSenhaConfirmada(null);
    setPasso(1);
  };

  const buscarCnpj = async () => {
    if (!infoCert?.documento || infoCert.documento.length !== 14) {
      setToast("Busca automática só funciona pra CNPJ. Preencha os campos manualmente.");
      return;
    }
    setBuscandoCnpj(true);
    try {
      const dados = await api.buscarCnpj(infoCert.documento);
      setNomeExibicao(dados.nome_fantasia || dados.razao_social);
      setCodigoMunicipio(dados.codigo_municipio_ibge || "");
    } catch (e) {
      setToast(`Não encontrei esse CNPJ: ${e.message}`);
    } finally {
      setBuscandoCnpj(false);
    }
  };

  const testarConexao = async () => {
    setTestando(true);
    try {
      const r = await api.testarConexaoCertificado(infoCert.caminho_pfx, senhaConfirmada);
      setToast(`✓ ${r.mensagem}`);
    } catch (e) {
      setToast(`Conexão falhou: ${e.message}`);
    } finally {
      setTestando(false);
    }
  };

  const salvar = async () => {
    if (!nomeExibicao || !im || !codigoMunicipio) { setToast("Preencha nome, inscrição municipal e código do município."); return; }
    // TSInscMun (tiposSimples_v1.01.xsd): 1 a 15 caracteres -- unico limite
    // confirmavel contra o leiaute nacional (cada prefeitura define seu
    // proprio formato de IM, entao nao da pra travar mais que isso).
    if (im.length > 15) { setToast("A inscrição municipal tem no máximo 15 caracteres (padrão do leiaute nacional)."); return; }
    setSalvando(true);
    try {
      await api.criarPrestador({
        nome_exibicao: nomeExibicao, cnpj: infoCert.documento, im, codigo_municipio: codigoMunicipio,
        regime, regime_especial_tributacao: regimeEspecial, cor,
        caminho_pfx: infoCert.caminho_pfx, senha: senhaConfirmada, valido_ate: infoCert.valido_ate,
      });
      onCriado();
    } catch (e) {
      setToast(`Não deu pra salvar: ${e.message}`);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal title="Novo prestador" onClose={onClose} width={620}>
      <Field label="1. Certificado digital A1 (.pfx)">
        <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
          <label style={{ ...inputStyle, flex: 1, display: "flex", alignItems: "center", gap: 8, cursor: "pointer", color: arquivo ? T.ink : T.inkSoft }}>
            <Upload size={15} />
            {arquivo ? arquivo.name : "Escolher arquivo .pfx…"}
            <input type="file" accept=".pfx,.p12" style={{ display: "none" }} onChange={(e) => setArquivo(e.target.files?.[0] || null)} />
          </label>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <input style={inputStyle} type="password" placeholder="Senha do certificado" value={senha} onChange={(e) => setSenha(e.target.value)} readOnly={!!infoCert} disabled={!!infoCert} />
          {!infoCert && <Btn primary disabled={lendo} onClick={lerCertificado}>{lendo ? "Lendo…" : "Ler certificado"}</Btn>}
        </div>
        {infoCert && (
          <p style={{ fontSize: 14.5, color: T.green, marginTop: 8 }}>
            Certificado lido: {infoCert.nome_titular} — válido até {infoCert.valido_ate}.{" "}
            <button onClick={trocarCertificado} style={{ border: "none", background: "transparent", color: T.inkSoft, textDecoration: "underline", cursor: "pointer", fontSize: 14.5, padding: 0 }}>Trocar certificado</button>
          </p>
        )}
      </Field>

      {passo >= 2 && (
        <>
          <Field label="CNPJ/CPF do prestador">
            <div style={{ display: "flex", gap: 10 }}>
              <input style={{ ...inputStyle, flex: 1 }} value={infoCert.documento || ""} readOnly />
              <Btn disabled={buscandoCnpj} onClick={buscarCnpj}>{buscandoCnpj ? "Buscando…" : "Buscar dados (CNPJ)"}</Btn>
            </div>
          </Field>
          <Field label="Nome de exibição"><input style={inputStyle} value={nomeExibicao} onChange={(e) => setNomeExibicao(e.target.value)} /></Field>
          <Field label="Inscrição municipal"><input style={inputStyle} value={im} onChange={(e) => setIm(e.target.value)} /></Field>
          <Field label="Município (código IBGE)"><input style={inputStyle} value={codigoMunicipio} onChange={(e) => setCodigoMunicipio(e.target.value)} /></Field>
          <Field label="Regime (Simples Nacional)">
            <select style={inputStyle} value={regime} onChange={(e) => setRegime(e.target.value)}>
              <option value="1">Não optante pelo Simples Nacional</option>
              <option value="2">Optante — MEI</option>
              <option value="3">Optante — ME ou EPP (Simples Nacional)</option>
            </select>
            <p style={{ color: T.inkSoft, fontSize: 13.5, margin: "7px 0 0" }}>
              Se for optante (MEI ou ME/EPP), o ISS já vai embutido na guia mensal do Simples (DAS) — o campo de
              alíquota nos serviços desse prestador fica travado automaticamente, sem precisar mexer em mais nada aqui.
            </p>
          </Field>
          <Field label="Regime especial de tributação">
            <select style={inputStyle} value={regimeEspecial} onChange={(e) => setRegimeEspecial(e.target.value)}>
              <option value="0">Nenhum</option>
              <option value="1">Cooperativa</option>
              <option value="2">Estimativa</option>
              <option value="3">Microempresa Municipal</option>
              <option value="4">Notário ou Registrador</option>
              <option value="5">Profissional Autônomo</option>
              <option value="6">Sociedade de Profissionais</option>
            </select>
          </Field>
          <Field label="Cor deste prestador">
            <div style={{ display: "flex", gap: 8 }}>
              {CORES_SUGERIDAS.map((c) => (
                <button key={c} onClick={() => setCor(c)} style={{ width: 28, height: 28, borderRadius: 99, background: c, border: cor === c ? `2.5px solid ${T.ink}` : "2.5px solid transparent", cursor: "pointer" }} />
              ))}
            </div>
          </Field>
          <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
            <Btn disabled={testando} onClick={testarConexao}>{testando ? "Testando…" : "Testar conexão (homologação)"}</Btn>
            <div style={{ flex: 1 }} />
            <Btn primary disabled={salvando} onClick={salvar}>{salvando ? "Salvando…" : "Salvar prestador"}</Btn>
          </div>
        </>
      )}
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Tomadores                                                     */
/* ------------------------------------------------------------------ */
function Tomadores({ prestador, setToast }) {
  const [tomadores, setTomadores] = useState([]);
  const [q, setQ] = useState("");
  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState(null);
  const [mostrarInativos, setMostrarInativos] = useState(false);

  const carregar = () => { if (prestador) api.listarTomadores(prestador.id, !mostrarInativos).then(setTomadores); };
  useEffect(carregar, [prestador?.id, mostrarInativos]);

  if (!prestador) return <AvisoSemPrestador kicker="Clientes de" title="Tomadores" />;
  const meus = tomadores.filter((t) => t.nome.toLowerCase().includes(q.toLowerCase()));

  const excluir = async (t) => {
    if (!window.confirm(`Excluir o tomador "${t.nome}"? Essa ação não pode ser desfeita.`)) return;
    try {
      await api.excluirTomador(prestador.id, t.id);
      setToast("✓ Tomador excluído");
      carregar();
    } catch (e) {
      // Tem nota/mensalidade vinculada -- exclusao definitiva bloqueada de
      // proposito (docs/auditoria.md, Bloco 4.1). Oferece inativar em vez
      // de so' mostrar o erro e travar o usuario.
      if (window.confirm(
        `${e.message}\n\nDeseja inativar este tomador em vez de excluir? Ele some da lista ativa, `
        + "mas o histórico de notas continua intacto e dá pra reativar depois."
      )) {
        try {
          await api.inativarTomador(prestador.id, t.id);
          setToast("✓ Tomador inativado");
          carregar();
        } catch (e2) {
          setToast(`Não deu pra inativar: ${e2.message}`);
        }
      }
    }
  };

  const reativar = async (t) => {
    try {
      await api.reativarTomador(prestador.id, t.id);
      setToast("✓ Tomador reativado");
      carregar();
    } catch (e) {
      setToast(`Não deu pra reativar: ${e.message}`);
    }
  };

  return (
    <>
      <ScreenTitle kicker="Clientes de" title="Tomadores" sub={prestador.nome_exibicao} corDot={prestador.cor} />
      <div style={{ display: "flex", gap: 12, marginBottom: 18 }}>
        <div style={{ position: "relative", flex: 1 }}>
          <Search size={16} style={{ position: "absolute", left: 13, top: 13, color: T.inkSoft }} />
          <input style={{ ...inputStyle, paddingLeft: 38 }} placeholder="Buscar tomador…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Btn primary onClick={() => setModalAberto(true)}><Plus size={16} /> Novo — só o CNPJ</Btn>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14.5, color: T.inkSoft, marginBottom: 12, cursor: "pointer" }}>
        <input type="checkbox" checked={mostrarInativos} onChange={(e) => setMostrarInativos(e.target.checked)} /> Mostrar inativos
      </label>
      <Card>
        {meus.length === 0 && <div style={{ padding: 20, color: T.inkSoft, fontSize: 15.5 }}>Nenhum tomador ainda.</div>}
        {meus.map((t, i) => (
          <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "15px 20px", borderBottom: i < meus.length - 1 ? `1px solid ${T.line}` : "none", opacity: t.ativo === 0 ? 0.55 : 1 }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, background: T.greenGhost, color: T.green, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: T.fontDisplay, fontWeight: 700 }}>
              {t.nome[0]}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{t.nome} {t.ativo === 0 && <span style={{ fontWeight: 400, color: T.inkSoft }}>(inativo)</span>}</div>
              <div style={{ color: T.inkSoft, fontSize: 14.5 }}>{t.doc} · {t.email || "sem e-mail"}</div>
            </div>
            {t.ativo === 0 ? (
              <Btn onClick={() => reativar(t)}>Reativar</Btn>
            ) : (
              <>
                <IconBtn title="Editar tomador" onClick={() => setEditando(t)}><Pencil size={16} /></IconBtn>
                <IconBtn title="Excluir tomador" onClick={() => excluir(t)}><Trash2 size={16} /></IconBtn>
              </>
            )}
          </div>
        ))}
      </Card>
      <p style={{ color: T.inkSoft, fontSize: 14.5, marginTop: 12 }}>
        Ao cadastrar, você digita só o CNPJ/CPF — razão social e endereço chegam sozinhos (CNPJ) ou você preenche à mão (CPF).
      </p>
      {modalAberto && (
        <NovoTomadorModal
          onClose={() => setModalAberto(false)}
          onCriado={() => { setModalAberto(false); carregar(); setToast("✓ Tomador cadastrado"); }}
          prestadorId={prestador.id}
          setToast={setToast}
        />
      )}
      {editando && (
        <NovoTomadorModal
          tomadorEditando={editando}
          onClose={() => setEditando(null)}
          onCriado={() => { setEditando(null); carregar(); setToast("✓ Tomador atualizado"); }}
          prestadorId={prestador.id}
          setToast={setToast}
        />
      )}
    </>
  );
}

function NovoTomadorModal({ onClose, onCriado, prestadorId, setToast, tomadorEditando }) {
  const editando = !!tomadorEditando;
  const [doc, setDoc] = useState(tomadorEditando?.doc || "");
  const [nome, setNome] = useState(tomadorEditando?.nome || "");
  const [email, setEmail] = useState(tomadorEditando?.email || "");
  const [telefone, setTelefone] = useState(tomadorEditando?.telefone || "");
  const [endereco, setEndereco] = useState(tomadorEditando?.endereco || "");
  const [retencoes, setRetencoes] = useState(() => retencoesDe(tomadorEditando));
  const [mostrarRetencoes, setMostrarRetencoes] = useState(
    () => Object.values(retencoesDe(tomadorEditando)).some(Boolean)
  );
  const [buscando, setBuscando] = useState(false);
  const [salvando, setSalvando] = useState(false);

  const buscar = async () => {
    const limpo = limparDocumento(doc);
    if (limpo.length === 11) { setToast("CPF não tem busca automática (dado protegido por lei) — preencha o nome à mão."); return; }
    if (limpo.length !== 14) { setToast("Digite um CNPJ (14 caracteres) ou CPF (11 números)."); return; }
    setBuscando(true);
    try {
      const dados = await api.buscarCnpj(limpo);
      setNome(dados.nome_fantasia || dados.razao_social);
      setEmail(dados.email || "");
      setTelefone(dados.telefone || "");
      setEndereco(dados.endereco_formatado || "");
    } catch (e) {
      setToast(`Não encontrei esse CNPJ: ${e.message}`);
    } finally {
      setBuscando(false);
    }
  };

  const salvar = async () => {
    const limpo = limparDocumento(doc);
    if (!nome) { setToast("Digite o nome do tomador."); return; }
    if (!editando && !validarCpfOuCnpj(limpo)) {
      setToast("Este CNPJ/CPF não é válido (dígito verificador não confere). Confira o número.");
      return;
    }
    setSalvando(true);
    try {
      const dados = { nome, email: email || null, telefone: telefone || null, endereco: endereco || null, retencoes };
      if (editando) {
        await api.editarTomador(prestadorId, tomadorEditando.id, dados);
      } else {
        await api.criarTomador(prestadorId, { doc: limpo, ...dados });
      }
      onCriado();
    } catch (e) {
      setToast(`Não deu pra salvar: ${e.message}`);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal title={editando ? "Editar tomador" : "Novo tomador"} onClose={onClose} width={520}>
      <Field label={editando ? "CNPJ/CPF (não muda)" : "CNPJ/CPF"}>
        <div style={{ display: "flex", gap: 10 }}>
          <input style={{ ...inputStyle, flex: 1 }} placeholder="Só números" value={doc} onChange={(e) => setDoc(e.target.value)} readOnly={editando} disabled={editando} />
          {!editando && <Btn disabled={buscando} onClick={buscar}>{buscando ? "Buscando…" : "Buscar"}</Btn>}
        </div>
      </Field>
      <Field label="Nome"><input style={inputStyle} maxLength={300} value={nome} onChange={(e) => setNome(e.target.value)} /></Field>
      <Field label="E-mail"><input style={inputStyle} value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label="Telefone"><input style={inputStyle} value={telefone} onChange={(e) => setTelefone(e.target.value)} /></Field>
      <Field label="Endereço"><input style={inputStyle} value={endereco} onChange={(e) => setEndereco(e.target.value)} /></Field>

      {!mostrarRetencoes ? (
        <button onClick={() => setMostrarRetencoes(true)} style={{ border: "none", background: "transparent", color: T.green, fontWeight: 600, fontSize: 14.5, cursor: "pointer", padding: 0, marginBottom: 18, display: "flex", alignItems: "center", gap: 6 }}>
          <ShieldCheck size={15} /> Este tomador retém imposto na fonte? (convênios costumam ter uma regra fixa)
        </button>
      ) : (
        <Field label="Este tomador retém imposto na fonte? (regra fixa, vale pra toda nota dele)">
          <CamposRetencao valores={retencoes} onChange={setRetencoes} />
        </Field>
      )}

      <Btn primary disabled={salvando} style={{ width: "100%", justifyContent: "center" }} onClick={salvar}>{salvando ? "Salvando…" : editando ? "Salvar alterações" : "Salvar tomador"}</Btn>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Mensalidades                                                  */
/* ------------------------------------------------------------------ */
function Mensalidades({ prestador, setToast }) {
  const [recorrencias, setRecorrencias] = useState([]);
  const [tomadores, setTomadores] = useState([]);
  const [modelos, setModelos] = useState([]);
  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState(null);

  const carregar = () => {
    if (!prestador) return;
    api.listarRecorrencias(prestador.id).then(setRecorrencias);
    api.listarTomadores(prestador.id).then(setTomadores);
    api.listarModelos(prestador.id).then(setModelos);
  };
  useEffect(carregar, [prestador?.id]);

  if (!prestador) return <AvisoSemPrestador kicker="Emissão automática" title="Mensalidades" />;
  const nomeTomador = (id) => tomadores.find((t) => t.id === id)?.nome || "?";
  const nomeModelo = (id) => modelos.find((m) => m.id === id)?.descricao || "?";

  const alternar = async (r) => {
    try {
      await api.alternarRecorrencia(prestador.id, r.id, !r.ativo);
      setToast(r.ativo ? "Mensalidade pausada" : "Mensalidade reativada");
      carregar();
    } catch (e) {
      setToast(`Erro: ${e.message}`);
    }
  };

  const excluir = async (r) => {
    if (!window.confirm(`Excluir a mensalidade de "${nomeTomador(r.tomador_id)}"? Essa ação não pode ser desfeita.`)) return;
    try {
      await api.excluirRecorrencia(prestador.id, r.id);
      setToast("✓ Mensalidade excluída");
      carregar();
    } catch (e) {
      setToast(`Não deu pra excluir: ${e.message}`);
    }
  };

  return (
    <>
      <ScreenTitle kicker="Emissão automática" title="Mensalidades" sub="No dia marcado, a nota sai sozinha — mesmo sem ninguém clicar." />
      <Card>
        {recorrencias.length === 0 && <div style={{ padding: 20, color: T.inkSoft, fontSize: 15.5 }}>Nenhuma mensalidade cadastrada.</div>}
        {recorrencias.map((r, i) => (
          <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "16px 20px", borderBottom: i < recorrencias.length - 1 ? `1px solid ${T.line}` : "none", opacity: r.ativo ? 1 : 0.5 }}>
            <div style={{ width: 44, textAlign: "center" }}>
              <div style={{ fontFamily: T.fontDisplay, fontSize: 21.5, fontWeight: 700 }}>{r.dia_do_mes}</div>
              <div style={{ fontSize: 12, color: T.inkSoft, textTransform: "uppercase", letterSpacing: ".05em" }}>dia</div>
            </div>
            <Dot cor={prestador.cor} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{nomeTomador(r.tomador_id)}</div>
              <div style={{ color: T.inkSoft, fontSize: 14.5 }}>{nomeModelo(r.modelo_id)}</div>
            </div>
            <div style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{BRL(r.valor)}</div>
            <Toggle on={!!r.ativo} onClick={() => alternar(r)} />
            <IconBtn title="Editar mensalidade" onClick={() => setEditando(r)}><Pencil size={16} /></IconBtn>
            <IconBtn title="Excluir mensalidade" onClick={() => excluir(r)}><Trash2 size={16} /></IconBtn>
          </div>
        ))}
      </Card>
      <div style={{ marginTop: 16 }}>
        <Btn primary onClick={() => setModalAberto(true)}><Plus size={16} /> Nova mensalidade</Btn>
      </div>
      {modalAberto && (
        <NovaMensalidadeModal
          onClose={() => setModalAberto(false)}
          onCriada={() => { setModalAberto(false); carregar(); setToast("✓ Mensalidade cadastrada"); }}
          prestadorId={prestador.id}
          tomadores={tomadores}
          modelos={modelos}
          setToast={setToast}
        />
      )}
      {editando && (
        <NovaMensalidadeModal
          recorrenciaEditando={editando}
          onClose={() => setEditando(null)}
          onCriada={() => { setEditando(null); carregar(); setToast("✓ Mensalidade atualizada"); }}
          prestadorId={prestador.id}
          tomadores={tomadores}
          modelos={modelos}
          setToast={setToast}
        />
      )}
    </>
  );
}

function NovaMensalidadeModal({ onClose, onCriada, prestadorId, tomadores, modelos, setToast, recorrenciaEditando }) {
  const editando = !!recorrenciaEditando;
  const [tomadorId, setTomadorId] = useState(recorrenciaEditando?.tomador_id ? String(recorrenciaEditando.tomador_id) : "");
  const [modeloId, setModeloId] = useState(recorrenciaEditando?.modelo_id ? String(recorrenciaEditando.modelo_id) : "");
  const [valor, setValor] = useState(formatarValorMonetario(recorrenciaEditando?.valor || ""));
  const [diaDoMes, setDiaDoMes] = useState(recorrenciaEditando?.dia_do_mes || 5);
  const [salvando, setSalvando] = useState(false);

  const escolherModelo = (id) => {
    setModeloId(id);
    const m = modelos.find((x) => String(x.id) === String(id));
    if (m) setValor(formatarValorMonetario(m.valor_padrao));
  };

  const salvar = async () => {
    if (!tomadorId || !modeloId || !valor) { setToast("Escolha o tomador, o serviço e confirme o valor."); return; }
    setSalvando(true);
    try {
      const dados = { tomador_id: Number(tomadorId), modelo_id: Number(modeloId), valor, dia_do_mes: Number(diaDoMes) };
      if (editando) {
        await api.editarRecorrencia(prestadorId, recorrenciaEditando.id, dados);
      } else {
        await api.criarRecorrencia(prestadorId, { ...dados, ativo: true });
      }
      onCriada();
    } catch (e) {
      setToast(`Não deu pra salvar: ${e.message}`);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal title={editando ? "Editar mensalidade" : "Nova mensalidade"} onClose={onClose} width={480}>
      <Field label="Tomador">
        <select style={inputStyle} value={tomadorId} onChange={(e) => setTomadorId(e.target.value)}>
          <option value="">Escolher…</option>
          {tomadores.map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
      </Field>
      <Field label="Serviço">
        <select style={inputStyle} value={modeloId} onChange={(e) => escolherModelo(e.target.value)}>
          <option value="">Escolher…</option>
          {modelos.map((m) => <option key={m.id} value={m.id}>{m.descricao}</option>)}
        </select>
      </Field>
      <Field label="Valor (R$)"><CampoValorMonetario value={valor} onChange={setValor} /></Field>
      <Field label="Dia do mês"><input style={inputStyle} type="number" min={1} max={28} value={diaDoMes} onChange={(e) => setDiaDoMes(e.target.value)} /></Field>
      <Btn primary disabled={salvando} style={{ width: "100%", justifyContent: "center" }} onClick={salvar}>{salvando ? "Salvando…" : editando ? "Salvar alterações" : "Salvar mensalidade"}</Btn>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Modelos de serviço                                            */
/* ------------------------------------------------------------------ */
function Servicos({ prestador, setToast }) {
  const [modelos, setModelos] = useState([]);
  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState(null);
  const carregar = () => { if (prestador) api.listarModelos(prestador.id).then(setModelos); };
  useEffect(carregar, [prestador?.id]);
  if (!prestador) return <AvisoSemPrestador kicker="Catálogo de" title="Serviços" />;

  const excluir = async (m) => {
    if (!window.confirm(`Excluir o serviço "${m.descricao}"? Essa ação não pode ser desfeita.`)) return;
    try {
      await api.excluirModelo(prestador.id, m.id);
      setToast("✓ Serviço excluído");
      carregar();
    } catch (e) {
      setToast(`Não deu pra excluir: ${e.message}`);
    }
  };

  return (
    <>
      <ScreenTitle kicker="Catálogo de" title="Serviços" sub={prestador.nome_exibicao} corDot={prestador.cor} />
      <Card>
        {modelos.length === 0 && <div style={{ padding: 20, color: T.inkSoft, fontSize: 15.5 }}>Nenhum modelo de serviço ainda.</div>}
        {modelos.map((m, i) => (
          <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "15px 20px", borderBottom: i < modelos.length - 1 ? `1px solid ${T.line}` : "none" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                {m.descricao}
                {m.precisa_revisao_cod_trib_municipal ? (
                  <span title="Código de tributação municipal inválido (formato antigo, 10 dígitos) — corrija antes de emitir uma nota com este serviço.">
                    <Tag icon={<AlertTriangle size={13} />} txt="revisar" warn />
                  </span>
                ) : null}
              </div>
              <div style={{ color: T.inkSoft, fontSize: 14.5 }}>Cód. nacional {m.cod_tributacao_nacional} · NBS {m.cod_nbs}</div>
            </div>
            <div style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{BRL(m.valor_padrao)}</div>
            <IconBtn title="Editar serviço" onClick={() => setEditando(m)}><Pencil size={16} /></IconBtn>
            <IconBtn title="Excluir serviço" onClick={() => excluir(m)}><Trash2 size={16} /></IconBtn>
          </div>
        ))}
      </Card>
      <div style={{ marginTop: 16 }}><Btn primary onClick={() => setModalAberto(true)}><Plus size={16} /> Novo serviço</Btn></div>
      {modalAberto && (
        <NovoModeloModal
          onClose={() => setModalAberto(false)}
          onCriado={() => { setModalAberto(false); carregar(); setToast("✓ Modelo de serviço cadastrado"); }}
          prestador={prestador}
          setToast={setToast}
        />
      )}
      {editando && (
        <NovoModeloModal
          modeloEditando={editando}
          onClose={() => setEditando(null)}
          onCriado={() => { setEditando(null); carregar(); setToast("✓ Serviço atualizado"); }}
          prestador={prestador}
          setToast={setToast}
        />
      )}
    </>
  );
}

function NovoModeloModal({ onClose, onCriado, prestador, setToast, modeloEditando }) {
  const editando = !!modeloEditando;
  const prestadorId = prestador.id;
  // opSimpNac: "2" MEI ou "3" ME/EPP -- optante do Simples Nacional. Nesses
  // casos o ISS vai dentro do DAS (guia única), não "por fora" na nota --
  // ver app/fiscal/dps_builder._pAliq_deve_ser_omitido pra base normativa
  // completa (regras E1302/E0625/E0631 do leiaute + LC 123/2006, art. 13
  // VIII e art. 18). O backend já garante isso no XML mesmo se este campo
  // tiver algo salvo -- travar aqui é só pra secretária nunca digitar um
  // valor que não vai valer nada (docs/auditoria.md, Bloco 2.3).
  const optanteSimples = prestador.regime === "2" || prestador.regime === "3";
  const [descricao, setDescricao] = useState(modeloEditando?.descricao || "");
  const [codNacional, setCodNacional] = useState(modeloEditando?.cod_tributacao_nacional || "");
  const [codMunicipal, setCodMunicipal] = useState(modeloEditando?.cod_tributacao_municipal || "");
  const [codNbs, setCodNbs] = useState(modeloEditando?.cod_nbs || "");
  const [valorPadrao, setValorPadrao] = useState(formatarValorMonetario(modeloEditando?.valor_padrao || ""));
  const [aliquota, setAliquota] = useState(modeloEditando?.aliquota || "");
  const [salvando, setSalvando] = useState(false);

  const salvar = async () => {
    // cTribMun e' OPCIONAL (XSD oficial, TCCServ: minOccurs="0") -- desdobro
    // MUNICIPAL do ISSQN, 3 digitos quando informado (TCCodTribMun,
    // tiposSimples_v1.01.xsd), nao 10 (docs/auditoria-2.md, secao 8.1). So'
    // valida o formato se o usuario digitou algo; em branco fica valido
    // (nem toda prefeitura tem um desdobro proprio).
    const codMunicipalValido = codMunicipal === "" || (codMunicipal.length === 3 && /^\d{3}$/.test(codMunicipal));
    if (!descricao || codNacional.length !== 6 || !codMunicipalValido || codNbs.length !== 9 || !valorPadrao) {
      setToast("Confira: descrição, código nacional (6 dígitos), municipal (3 dígitos ou em branco), NBS (9 dígitos) e valor.");
      return;
    }
    setSalvando(true);
    try {
      const dados = {
        descricao, cod_tributacao_nacional: codNacional, cod_tributacao_municipal: codMunicipal,
        cod_nbs: codNbs, valor_padrao: valorPadrao,
        // optante do Simples nunca manda aliquota, mesmo que o campo tenha
        // algo digitado de antes (defesa em profundidade, o backend tambem trava isso)
        aliquota: optanteSimples ? null : (aliquota || null),
      };
      if (editando) {
        await api.editarModelo(prestadorId, modeloEditando.id, dados);
      } else {
        await api.criarModelo(prestadorId, dados);
      }
      onCriado();
    } catch (e) {
      setToast(`Não deu pra salvar: ${e.message}`);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal title={editando ? "Editar serviço" : "Novo modelo de serviço"} onClose={onClose} width={480}>
      <Field label="Descrição"><input style={inputStyle} maxLength={2000} value={descricao} onChange={(e) => setDescricao(e.target.value)} /></Field>
      <Field label="Código de tributação nacional (6 dígitos)">
        <input
          style={inputStyle} value={codNacional} list="lista-cod-trib-nacional-saude"
          placeholder="Escolha da lista ou digite"
          onChange={(e) => setCodNacional(e.target.value.replace(/\D/g, "").slice(0, 6))}
        />
        <datalist id="lista-cod-trib-nacional-saude">
          {CODIGOS_TRIBUTACAO_NACIONAL_SAUDE.map(([codigo, desc]) => (
            <option key={codigo} value={codigo} label={`${codigo} — ${desc}`} />
          ))}
        </datalist>
      </Field>
      <Field label="Código de tributação municipal (3 dígitos — deixe em branco se a prefeitura não exigir)">
        <input
          style={inputStyle} value={codMunicipal}
          onChange={(e) => setCodMunicipal(e.target.value.replace(/\D/g, "").slice(0, 3))}
        />
      </Field>
      {modeloEditando?.precisa_revisao_cod_trib_municipal ? (
        <div style={{ ...inputStyle, height: "auto", background: T.paper, color: T.inkSoft, display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 12, padding: 10 }}>
          <ShieldCheck size={15} style={{ flexShrink: 0, marginTop: 2 }} />
          <span>
            O código de tributação municipal deste serviço foi cadastrado antigamente com 10 dígitos —
            mas o Sistema Nacional NFS-e exige exatamente 3 dígitos (ou nenhum, se a prefeitura não tiver
            um código próprio de ISSQN além do nacional). Corrija (ou apague) esse campo antes de salvar;
            enquanto não corrigir, o programa vai recusar emitir qualquer nota nova com este serviço.
          </span>
        </div>
      ) : null}
      <Field label="Código NBS (9 dígitos)"><input style={inputStyle} value={codNbs} onChange={(e) => setCodNbs(e.target.value)} /></Field>
      <Field label="Valor padrão (R$)"><CampoValorMonetario value={valorPadrao} onChange={setValorPadrao} /></Field>
      {optanteSimples ? (
        <Field label="Alíquota ISS">
          <div style={{ ...inputStyle, background: T.paper, color: T.inkSoft, display: "flex", alignItems: "center", gap: 8 }}>
            <ShieldCheck size={15} style={{ flexShrink: 0 }} /> Não se aplica — este prestador é optante do Simples Nacional, o ISS já vem embutido na guia mensal (DAS), não é calculado nota a nota.
          </div>
        </Field>
      ) : (
        <Field label="Alíquota ISS % (deixe em branco se o município já parametriza)">
          <input style={inputStyle} value={aliquota} onChange={(e) => setAliquota(e.target.value)} />
        </Field>
      )}
      <Btn primary disabled={salvando} style={{ width: "100%", justifyContent: "center" }} onClick={salvar}>{salvando ? "Salvando…" : editando ? "Salvar alterações" : "Salvar modelo"}</Btn>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Histórico                                                     */
/* ------------------------------------------------------------------ */
function Historico({ prestador, setToast }) {
  const [notas, setNotas] = useState([]);
  const carregar = () => { if (prestador) api.listarNotas(prestador.id).then(setNotas); };
  useEffect(carregar, [prestador?.id]);
  if (!prestador) return <AvisoSemPrestador kicker="Todas as notas" title="Histórico" />;

  const abrirPasta = (n) => setToast(`Arquivo: ${n.xml_path?.split("\\").slice(-1)[0] || "—"} (abrir pasta só funciona no app desktop)`);

  const reenviar = async (n) => {
    try {
      await api.reenviarEmail(prestador.id, n.id);
      setToast("E-mail reenviado ao tomador");
      carregar();
    } catch (e) {
      setToast(`Erro ao reenviar: ${e.message}`);
    }
  };

  const whatsapp = (n) => {
    const tel = (n.tomador_telefone || "").replace(/\D/g, "");
    if (!tel) { setToast("Este tomador não tem telefone cadastrado."); return; }
    const numero = tel.startsWith("55") ? tel : `55${tel}`;
    const msg = encodeURIComponent(`Olá ${n.tomador_nome}, segue sua nota fiscal (NFS-e ${n.numero_dps}), no valor de R$ ${n.valor}.`);
    window.open(`https://wa.me/${numero}?text=${msg}`, "_blank");
  };

  return (
    <>
      <ScreenTitle kicker="Todas as notas" title="Histórico" sub={prestador.nome_exibicao} corDot={prestador.cor} />
      <Card style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 16 }}>
          <thead>
            <tr style={{ textAlign: "left", color: T.inkSoft, fontSize: 13.5, textTransform: "uppercase", letterSpacing: ".05em" }}>
              {["Nº", "Tomador", "Valor", "Data", "Status", ""].map((h) => (
                <th key={h} style={{ padding: "14px 18px", borderBottom: `1px solid ${T.line}`, fontWeight: 700 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {notas.length === 0 && (
              <tr><td colSpan={6} style={{ padding: 20, color: T.inkSoft }}>Nenhuma nota ainda.</td></tr>
            )}
            {notas.map((n) => (
              <tr key={n.id}>
                <td style={td}>{n.numero_dps}</td>
                <td style={td}>{n.tomador_nome}</td>
                <td style={{ ...td, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{BRL(n.valor)}</td>
                <td style={{ ...td, color: T.inkSoft }}>{(n.emitida_em || n.criada_em || "").slice(0, 10)}</td>
                <td style={td}><StatusPill status={n.status} /></td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <IconBtn title="Ver caminho do arquivo" onClick={() => abrirPasta(n)}><FolderOpen size={16} /></IconBtn>
                  <IconBtn title="Reenviar e-mail" disabled={n.status !== "emitida" || !n.tomador_email} onClick={() => reenviar(n)}><Mail size={16} /></IconBtn>
                  <IconBtn title="WhatsApp" onClick={() => whatsapp(n)}><MessageCircle size={16} /></IconBtn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Tela: Configurações                                                 */
/* ------------------------------------------------------------------ */
function Config({ setToast }) {
  const [pastaBase, setPastaBase] = useState("");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpUsuario, setSmtpUsuario] = useState("");
  const [smtpSenha, setSmtpSenha] = useState("");
  const [senhaJaConfigurada, setSenhaJaConfigurada] = useState(false);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    api.obterConfig().then((c) => {
      setPastaBase(c.pasta_base || "");
      setSmtpHost(c.smtp_host || "");
      setSmtpUsuario(c.smtp_usuario || "");
      setSenhaJaConfigurada(!!c.smtp_senha_configurada);
    });
  }, []);

  const salvar = async () => {
    setSalvando(true);
    try {
      await api.salvarConfig({
        pasta_base: pastaBase, smtp_host: smtpHost, smtp_porta: 587,
        smtp_usuario: smtpUsuario, smtp_senha: smtpSenha || undefined,
      });
      setToast("✓ Configurações salvas");
    } catch (e) {
      setToast(`Erro: ${e.message}`);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <>
      <ScreenTitle kicker="Ajustes" title="Configurações" sub="Uma vez configurado, esquece que existe." />
      <div style={{ display: "grid", gap: 16, maxWidth: 640 }}>
        <Card style={{ padding: 24 }}>
          <Field label="Pasta onde as notas são salvas">
            <input style={inputStyle} value={pastaBase} onChange={(e) => setPastaBase(e.target.value)} />
          </Field>
          <p style={{ fontSize: 14.5, color: T.inkSoft, margin: 0 }}>💡 Aponte para uma pasta do OneDrive/Google Drive e ganhe backup automático na nuvem.</p>
        </Card>
        <Card style={{ padding: 24 }}>
          <Field label="E-mail que envia as notas (SMTP)">
            <input style={inputStyle} placeholder="smtp.gmail.com" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} />
          </Field>
          <Field label="Usuário (e-mail)">
            <input style={inputStyle} value={smtpUsuario} onChange={(e) => setSmtpUsuario(e.target.value)} />
          </Field>
          <Field label={senhaJaConfigurada ? "Senha de app (já configurada — digite só se quiser trocar)" : "Senha de app"}>
            <input style={inputStyle} type="password" placeholder={senhaJaConfigurada ? "••••••••••••••••" : ""} value={smtpSenha} onChange={(e) => setSmtpSenha(e.target.value)} />
          </Field>
        </Card>
        <Card style={{ padding: 24, border: `1.5px solid ${T.line}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 16.5 }}>Ambiente de emissão</div>
              <div style={{ fontSize: 15, color: T.inkSoft, marginTop: 3 }}>Homologação — modo de teste, notas sem validade</div>
            </div>
            <Toggle on={false} disabled onClick={() => setToast("Por segurança, essa troca não é feita por um botão — veja o README (seção 10) pra trocar pra produção de verdade.")} />
          </div>
        </Card>
        <div><Btn primary disabled={salvando} onClick={salvar}>{salvando ? "Salvando…" : "Salvar configurações"}</Btn></div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Shell                                                               */
/* ------------------------------------------------------------------ */
const NAV = [
  { id: "dia", label: "Meu Dia", icon: Sun },
  { id: "emitir", label: "Emitir nota", icon: FileText },
  { id: "prestadores", label: "Prestadores", icon: Stethoscope },
  { id: "tomadores", label: "Tomadores", icon: Users },
  { id: "servicos", label: "Serviços", icon: FileText },
  { id: "mensal", label: "Mensalidades", icon: Repeat },
  { id: "hist", label: "Histórico", icon: History },
  { id: "config", label: "Configurações", icon: Settings },
];

export default function App() {
  const [backendOk, setBackendOk] = useState(null); // null = checando, true/false = resultado
  const [screen, setScreen] = useState("dia");
  const [prestadores, setPrestadores] = useState([]);
  const [prestadorId, setPrestadorId] = useState(null);
  const [selOpen, setSelOpen] = useState(false);
  const [toast, setToastRaw] = useState(null);
  const setToast = (msg) => { setToastRaw(msg); setTimeout(() => setToastRaw(null), 3800); };

  const recarregarPrestadores = () => api.listarPrestadores().then((lista) => {
    setPrestadores(lista);
    if (!prestadorId && lista.length) setPrestadorId(lista[0].id);
  });

  useEffect(() => {
    api.health()
      .then(() => { setBackendOk(true); recarregarPrestadores(); })
      .catch(() => setBackendOk(false));
  }, []);

  if (backendOk === null) {
    return <TelaCentral><p style={{ color: T.inkSoft }}>Conectando ao backend…</p></TelaCentral>;
  }
  if (backendOk === false) {
    return (
      <TelaCentral>
        <AlertTriangle size={32} color={T.red} />
        <h2 style={{ fontFamily: T.fontDisplay }}>Não consegui falar com o backend</h2>
        <p style={{ color: T.inkSoft, maxWidth: 420, textAlign: "center" }}>
          Abra um terminal, ative o ambiente virtual do projeto e rode <code>python -m app.api</code> —
          essa janela precisa ficar aberta enquanto você usa o protótipo.
        </p>
        <Btn primary onClick={() => location.reload()}>Tentar de novo</Btn>
      </TelaCentral>
    );
  }

  const prestador = prestadores.find((p) => p.id === prestadorId) || null;

  const screens = {
    dia: <MeuDia setToast={setToast} />,
    emitir: <EmitirNota prestador={prestador} setToast={setToast} />,
    prestadores: <Prestadores prestadores={prestadores} recarregarPrestadores={recarregarPrestadores} setToast={setToast} />,
    tomadores: <Tomadores prestador={prestador} setToast={setToast} />,
    servicos: <Servicos prestador={prestador} setToast={setToast} />,
    mensal: <Mensalidades prestador={prestador} setToast={setToast} />,
    hist: <Historico prestador={prestador} setToast={setToast} />,
    config: <Config setToast={setToast} />,
  };

  return (
    <div className="ntf-shell" style={{ fontFamily: T.fontBody, background: T.paper, minHeight: "100vh", display: "flex", color: T.ink }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;600;700&family=Instrument+Sans:wght@400;500;600;700&display=swap');
        html { -webkit-text-size-adjust: 100%; }
        * { box-sizing: border-box; }
        button:hover { opacity: .92; }
        @keyframes toastIn { from { transform: translateY(12px); opacity: 0 } to { transform: translateY(0); opacity: 1 } }

        /* Responsivo: telas menores (tablet/notebook pequeno) */
        @media (max-width: 900px) {
          .ntf-shell { flex-direction: column !important; }
          .ntf-sidebar { width: 100% !important; min-height: auto !important; flex-direction: row !important; flex-wrap: wrap; align-items: center; padding: 12px 14px !important; }
          .ntf-sidebar-logo { border-bottom: none !important; margin-bottom: 0 !important; padding: 0 10px 0 0 !important; flex-shrink: 0; }
          .ntf-nav { display: flex !important; flex-wrap: wrap; gap: 4px; flex: 1 1 auto; }
          .ntf-nav button { width: auto !important; margin-bottom: 0 !important; }
          .ntf-sidebar-footer { display: none !important; }
          .ntf-topbar { flex-wrap: wrap; padding: 12px 16px !important; }
          .ntf-content { padding: 18px 16px !important; }
          .ntf-emitir-grid { grid-template-columns: 1fr !important; }
        }
        /* Responsivo: telas bem estreitas (celular) */
        @media (max-width: 560px) {
          .ntf-nav-label { display: none; }
          .ntf-nav button { padding: 10px !important; }
        }
      `}</style>

      {/* Sidebar */}
      <aside className="ntf-sidebar" style={{ width: 232, background: T.greenDark, color: "#E8EFE9", display: "flex", flexDirection: "column", padding: "22px 14px", flexShrink: 0, minHeight: "100vh" }}>
        <div className="ntf-sidebar-logo" style={{ padding: "0 10px 22px", borderBottom: "1px solid rgba(255,255,255,.12)", marginBottom: 14 }}>
          <div style={{ fontFamily: T.fontDisplay, fontSize: 22.5, fontWeight: 700, letterSpacing: "-.01em" }}>
            Nota<span style={{ color: "#8FD3A8" }}>Fácil</span>
          </div>
          <div style={{ fontSize: 13, opacity: 0.65, marginTop: 3 }}>emissor automático de NFS-e</div>
        </div>
        <div className="ntf-nav">
          {NAV.map((n) => {
            const Active = screen === n.id;
            const Icon = n.icon;
            return (
              <button key={n.id} onClick={() => setScreen(n.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 11, width: "100%", textAlign: "left",
                  padding: "11px 12px", marginBottom: 3, borderRadius: 10, border: "none", cursor: "pointer",
                  fontFamily: T.fontBody, fontSize: 16, fontWeight: Active ? 700 : 500,
                  background: Active ? "rgba(255,255,255,.12)" : "transparent",
                  color: Active ? "#fff" : "rgba(232,239,233,.78)",
                }}>
                <Icon size={17} /> <span className="ntf-nav-label">{n.label}</span>
              </button>
            );
          })}
        </div>
        <div className="ntf-sidebar-footer" style={{ marginTop: "auto", padding: "12px 10px", fontSize: 13, opacity: 0.6, lineHeight: 1.5 }}>
          🔒 Certificados guardados só neste computador, em Documentos\Emissor NFS-e\certificados\ — nada sobe pra nuvem.
        </div>
      </aside>

      {/* Main */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Topbar */}
        <div className="ntf-topbar" style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 32px", borderBottom: `1px solid ${T.line}`, background: "rgba(255,255,255,.6)", backdropFilter: "blur(6px)" }}>
          <div style={{ position: "relative" }}>
            <button onClick={() => setSelOpen(!selOpen)}
              style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 14px", borderRadius: 10, border: `1.5px solid ${T.line}`, background: "#fff", cursor: "pointer", fontFamily: T.fontBody, fontSize: 15.5, fontWeight: 600, color: T.ink }}>
              {prestador ? <><Dot cor={prestador.cor} /> {prestador.nome_exibicao}</> : "Nenhum prestador cadastrado"} <ChevronDown size={15} color={T.inkSoft} />
            </button>
            {selOpen && (
              <div style={{ position: "absolute", top: 46, left: 0, background: "#fff", border: `1px solid ${T.line}`, borderRadius: 12, boxShadow: "0 10px 30px rgba(20,30,25,.12)", zIndex: 20, minWidth: 240, overflow: "hidden" }}>
                {prestadores.map((p) => (
                  <button key={p.id} onClick={() => { setPrestadorId(p.id); setSelOpen(false); }}
                    style={{ display: "flex", gap: 10, alignItems: "center", width: "100%", padding: "12px 14px", border: "none", background: p.id === prestadorId ? T.paper : "#fff", cursor: "pointer", fontFamily: T.fontBody, fontSize: 15.5, textAlign: "left" }}>
                    <Dot cor={p.cor} />
                    <span><b>{p.nome_exibicao}</b></span>
                  </button>
                ))}
                {prestadores.length === 0 && <div style={{ padding: 14, fontSize: 14.5, color: T.inkSoft }}>Cadastre um prestador na aba "Prestadores".</div>}
              </div>
            )}
          </div>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 13.5, fontWeight: 700, letterSpacing: ".05em", background: T.amberGhost, color: T.amber, padding: "6px 12px", borderRadius: 99 }}>
            MODO TESTE (homologação)
          </span>
        </div>

        <div className="ntf-content" style={{ padding: "30px 32px", maxWidth: 1060, width: "100%", margin: "0 auto" }}>
          {screens[screen]}
        </div>
      </main>

      {/* Toast */}
      {toast && (
        <div style={{ position: "fixed", bottom: 26, left: "50%", transform: "translateX(-50%)", background: T.greenDark, color: "#fff", padding: "13px 22px", borderRadius: 12, fontFamily: T.fontBody, fontSize: 16, fontWeight: 600, boxShadow: "0 12px 30px rgba(10,40,30,.35)", animation: "toastIn .25s ease", zIndex: 300, maxWidth: "min(560px, calc(100vw - 32px))", textAlign: "center" }}>
          {toast}
        </div>
      )}
    </div>
  );
}

const TelaCentral = ({ children }) => (
  <div style={{ fontFamily: T.fontBody, background: T.paper, minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, color: T.ink, padding: 24 }}>
    {children}
  </div>
);
