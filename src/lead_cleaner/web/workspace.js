Object.assign(translations.zh, {inboxTitle:"会话收件箱",newConversation:"新建会话",refreshConversations:"刷新列表",operatorAccess:"操作员访问",connect:"连接",saveDraft:"保存修改",approveDraft:"审核通过",rejectDraft:"驳回",recordSentTitle:"记录人工已发送（不会代发）",recordSent:"记录回执",syncReviewedConversation:"同步已审核版本到 Notion"});
Object.assign(translations.en, {inboxTitle:"Conversations",newConversation:"New conversation",refreshConversations:"Refresh list",operatorAccess:"Operator access",connect:"Connect",saveDraft:"Save changes",approveDraft:"Approve",rejectDraft:"Reject",recordSentTitle:"Record a manual send (does not send)",recordSent:"Record receipt",syncReviewedConversation:"Sync reviewed version to Notion"});
Object.assign(factLabels, {hotel_tier:["酒店等级","Hotel tier"],vehicle:["用车需求","Vehicle"],guide_language:["导游语言","Guide language"],duration_days:["行程天数","Trip duration"]});

function newConversationKey() { return crypto.randomUUID(); }
function pendingMessage(payload) {
  const pending = JSON.parse(sessionStorage.getItem("leadflow.pending") || "null");
  if (pending) {
    const withoutId = (p) => JSON.stringify({...p,external_message_id:""});
    if (withoutId(pending) !== withoutId(payload)) throw new Error("上一条消息结果尚未确认，请先用原内容重试。 / Retry the pending message unchanged first.");
    return pending;
  }
  sessionStorage.setItem("leadflow.pending",JSON.stringify(payload));
  return payload;
}
async function requestJson(url,options={}) {
  const response = await apiFetch(url,options), data = await response.json();
  if (!response.ok) throw new Error(data.detail?.message || data.detail || "Request failed");
  return data;
}
function restoreInputs(data) {
  $("conversationIdInput").value = data.external_conversation_id;
  $("conversationChannel").value = data.channel;
  $("conversationSenderName").value = data.sender_name || "";
  $("conversationSenderEmail").value = data.sender_email || "";
  $("conversationSubject").value = data.subject || "";
  $("conversationSubject").parentElement.classList.toggle("hidden",data.channel !== "email");
}
async function refreshConversationList() {
  try {
    const list = await requestJson("/conversations");
    $("conversationList").replaceChildren();
    for (const entry of list) {
      const button = document.createElement("button");
      button.className = "inbox-item";
      button.textContent = (entry.sender_name || entry.external_conversation_id) + " · " + entry.turn_number;
      button.onclick = () => openConversation(entry);
      $("conversationList").append(button);
    }
    const active = sessionStorage.getItem("leadflow.active");
    if (!state.conversation.id && active && !sessionStorage.getItem("leadflow.pending")) {
      const entry = list.find((item) => item.conversation_id === active);
      if (entry) await openConversation(entry);
    }
    const session = await requestJson("/session");
    state.workspaceRole = session.role;
    renderReviewState();
    $("workspaceMode").textContent = session.role === "guest" ? "隔离离线演示 / Isolated offline demo" : "操作员工作区 / Operator workspace";
  } catch (error) { $("workspaceMode").textContent = error.message; }
}
async function openConversation(entry) {
  try {
    const data = await requestJson("/conversations/" + entry.conversation_id + "/latest");
    restoreInputs(entry);
    state.conversation = {id:entry.conversation_id,turn:data.turn_number,data,timeline:[]};
    sessionStorage.setItem("leadflow.active",entry.conversation_id);
    renderConversation(data,[]); renderReviewState();
    try {
      state.conversation.timeline = await loadConversationTimeline(entry.conversation_id);
      renderConversation(data,state.conversation.timeline); renderReviewState();
    } catch (error) { $("conversationError").textContent = error.message; }
  } catch (error) { $("conversationError").textContent = error.message; }
}
function renderReviewState() {
  const data = state.conversation.data, draft = data?.reply_draft;
  if (!draft) return;
  const score = data.current_analysis?.analysis_result?.decision?.lead_score;
  const dirty = $("conversationDraft").value !== draft.body_text;
  $("draftReviewState").textContent = "v" + draft.draft_version + " · " + draft.status +
    " · " + (state.lang === "zh" ? "累计评分 " : "Opportunity score ") + score +
    (dirty ? (state.lang === "zh" ? " · 有未保存修改" : " · Unsaved changes") : "") +
    (draft.internal_note ? " · " + draft.internal_note : "");
  const locked = ["suppressed","sent"].includes(draft.status);
  $("conversationDraft").disabled = locked; $("copyConversationDraft").disabled = !draft.body_text;
  document.querySelectorAll("[data-review]").forEach((button) => {
    button.disabled = locked || (button.dataset.review === "record_sent" && (dirty || draft.status !== "approved" || state.workspaceRole === "guest"));
  });
  $("syncConversation").disabled = dirty || !["approved","sent"].includes(draft.status) || !state.notionConfigured || state.workspaceRole === "guest";
}
$('conversationDraft').addEventListener('input', renderReviewState);
document.querySelectorAll("[data-review]").forEach((button) => {
  button.onclick = async () => {
    const data = state.conversation.data, draft = data?.reply_draft;
    if (!draft) return;
    try {
      const action = button.dataset.review, payload = {expected_version:draft.draft_version,action};
      if (action === "record_sent") payload.external_receipt = $("sendReceipt").value.trim();
      else payload.body_text = $("conversationDraft").value;
      button.disabled = true;
      data.reply_draft = await requestJson("/conversations/" + data.conversation_id + "/drafts/" + draft.draft_id + "/review",
        {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      renderReviewState();
      try { state.conversation.timeline = await loadConversationTimeline(data.conversation_id);
        renderConversation(data,state.conversation.timeline); renderReviewState();
      } catch (error) { $("conversationError").textContent = error.message; }
    } catch (error) { $("conversationError").textContent = error.message; renderReviewState(); }
  };
});
$("syncConversation").onclick = async () => {
  const data = state.conversation.data, draft = data.reply_draft;
  $("syncConversation").disabled = true;
  try {
    const result = await requestJson("/crm/notion/conversations/" + data.conversation_id,
      {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({draft_id:draft.draft_id,expected_version:draft.draft_version})});
    $("conversationError").textContent = "Notion · " + result.status;
  } catch (error) { $("conversationError").textContent = error.message; }
  finally { renderReviewState(); }
};
$("newConversation").onclick = () => {
  if (sessionStorage.getItem("leadflow.pending") && !confirm("旧消息可能仍在处理。确认放弃重试并新建会话？ / Leave the pending request?")) return;
  sessionStorage.removeItem("leadflow.pending"); sessionStorage.removeItem("leadflow.active");
  state.conversation = {id:"",turn:0,data:null,timeline:[]};
  $("conversationForm").reset(); $("conversationIdInput").value = newConversationKey();
  $("conversationOutput").classList.add("hidden"); $("conversationEmpty").classList.remove("hidden");
  $("conversationError").textContent = "";
};
$("refreshConversations").onclick = refreshConversationList;
$("setOperatorToken").onclick = () => {
  const token = $("operatorToken").value.trim();
  if (token) sessionStorage.setItem("leadflow.access",token); else sessionStorage.removeItem("leadflow.access");
  $("operatorToken").value = ""; state.conversation.id = ""; refreshConversationList(); checkNotion();
};
$("languageToggle").addEventListener("click",renderReviewState);
$("conversationIdInput").value = newConversationKey();
const pending = JSON.parse(sessionStorage.getItem("leadflow.pending") || "null");
if (pending) { restoreInputs(pending); $("conversationMessage").value = pending.message; }
applyLanguage(); refreshConversationList();
