<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
const API = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api'
const projects = ref([]), projectId = ref(1), docs = ref([]), sessions = ref([]), sessionId = ref(null), systemStatus = ref({llm_configured:false,llm_reachable:null,llm_model:null,llm_message:'点击测试连接'}), question = ref(''), messages = ref([]), loading = ref(false), testingModel = ref(false), fileInput = ref(null), newProject = ref({name:'',repo_url:''}), editProject = ref({name:'',description:'',repo_url:''}), repositoryUrl = ref(''), reasoningEffort = ref('auto'), messagesEl = ref(null), gridEl = ref(null), sidebarWidth = ref(330), autoFollow = ref(true)
let projectPoller = null, scrollFrame = null, stopResize = null
const activeProject = ()=>projects.value.find(project=>project.id===projectId.value)
const isImporting = ()=>['queued','importing'].includes(activeProject()?.repo_status)
const documentGroups = computed(()=>[
  {key:'repository',label:'仓库代码与结构',open:true,items:docs.value.filter(doc=>doc.source_type?.startsWith('repository_'))},
  {key:'github',label:'GitHub 动态',open:false,items:docs.value.filter(doc=>doc.source_type?.startsWith('github_'))},
  {key:'upload',label:'手动上传',open:true,items:docs.value.filter(doc=>!doc.source_type?.startsWith('repository_')&&!doc.source_type?.startsWith('github_'))},
].filter(group=>group.items.length))
const activeReply = computed(()=>messages.value.at(-1)?.role==='assistant'?messages.value.at(-1):null)
const activeStage = computed(()=>activeReply.value?.stages?.at(-1)||null)
function renderMarkdown(text){ return DOMPurify.sanitize(marked.parse(text || '')) }
function handleMessagesScroll(){ const el=messagesEl.value; if(el) autoFollow.value=el.scrollHeight-el.scrollTop-el.clientHeight<72 }
function scrollToLatest(force=false){
  if(force) autoFollow.value=true
  if(scrollFrame) return
  scrollFrame=requestAnimationFrame(async()=>{ scrollFrame=null; await nextTick(); const el=messagesEl.value; if(el&&(force||autoFollow.value)) el.scrollTop=el.scrollHeight })
}
function startResize(event){
  if(window.innerWidth<=800) return
  event.preventDefault()
  const rect=gridEl.value.getBoundingClientRect()
  document.body.classList.add('resizing-layout')
  const move=e=>{ sidebarWidth.value=Math.min(520,Math.max(260,e.clientX-rect.left)); localStorage.setItem('atlas-sidebar-width',String(sidebarWidth.value)) }
  const up=()=>{ window.removeEventListener('pointermove',move); window.removeEventListener('pointerup',up); document.body.classList.remove('resizing-layout'); stopResize=null }
  stopResize=up
  window.addEventListener('pointermove',move)
  window.addEventListener('pointerup',up)
}
function resetSidebar(){ sidebarWidth.value=330; localStorage.setItem('atlas-sidebar-width','330') }
function resizeWithKeyboard(event){
  if(!['ArrowLeft','ArrowRight','Home'].includes(event.key)) return
  event.preventDefault()
  sidebarWidth.value=event.key==='Home'?330:Math.min(520,Math.max(260,sidebarWidth.value+(event.key==='ArrowRight'?20:-20)))
  localStorage.setItem('atlas-sidebar-width',String(sidebarWidth.value))
}
async function loadProjects(){ projects.value = await fetch(`${API}/projects`).then(r=>r.json()); if(projects.value.length && !projects.value.some(p=>p.id===projectId.value)) projectId.value=projects.value[0].id }
async function loadDocs(){ docs.value = await fetch(`${API}/documents?project_id=${projectId.value}`).then(r=>r.json()) }
async function loadSessions(){ sessions.value = await fetch(`${API}/sessions?project_id=${projectId.value}`).then(r=>r.json()) }
async function loadSystemStatus(check=false){ systemStatus.value = await fetch(`${API}/system/status?check=${check}`).then(r=>r.json()); if(systemStatus.value.llm_reasoning_effort) reasoningEffort.value=systemStatus.value.llm_reasoning_effort }
async function testModel(){ testingModel.value=true; await loadSystemStatus(true); testingModel.value=false }
function syncProjectForm(){ const project=activeProject(); editProject.value={name:project?.name||'',description:project?.description||'',repo_url:project?.repo_url||''}; repositoryUrl.value=project?.repo_url||'' }
async function changeProject(){ messages.value=[]; sessionId.value=null; syncProjectForm(); await Promise.all([loadDocs(),loadSessions()]) }
async function updateProject(){ const current=activeProject(); const payload={name:editProject.value.name.trim(),description:editProject.value.description.trim(),repo_url:editProject.value.repo_url.trim()||null}; if(!payload.name) return; const repoChanged=(current?.repo_url||null)!==payload.repo_url; const r=await fetch(`${API}/projects/${projectId.value}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const d=await r.json(); if(!r.ok){alert(d.detail);return} await loadProjects(); syncProjectForm(); if(repoChanged&&payload.repo_url) await importRepository() }
async function createProject(){ const name=newProject.value.name.trim(); if(!name) return; const slug=`${name.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g,'-')}-${Date.now().toString().slice(-5)}`; const r=await fetch(`${API}/projects`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,slug,repo_url:newProject.value.repo_url.trim()||null})}); const d=await r.json(); if(!r.ok){alert(d.detail);return} newProject.value={name:'',repo_url:''}; await loadProjects(); projectId.value=d.id; await changeProject() }
async function deleteProject(){ const project=activeProject(); if(!project||isImporting()) return; if(!confirm(`确定删除工作区“${project.name}”？\n\n关联文档、对话、索引和本地仓库快照会一并删除，此操作无法撤销。`)) return; const r=await fetch(`${API}/projects/${project.id}`,{method:'DELETE'}); const d=await r.json(); if(!r.ok){alert(d.detail);return} messages.value=[]; await loadProjects(); if(projects.value.length){ projectId.value=projects.value[0].id; await changeProject() } else { docs.value=[]; repositoryUrl.value='' } }
async function importRepository(){ const r=await fetch(`${API}/projects/${projectId.value}/import-repository`,{method:'POST'}); const d=await r.json(); if(!r.ok) alert(d.detail); await loadProjects() }
async function saveRepository(){ const repo_url=repositoryUrl.value.trim(); if(!repo_url) return; const r=await fetch(`${API}/projects/${projectId.value}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url})}); const d=await r.json(); if(!r.ok){alert(d.detail);return} await loadProjects(); repositoryUrl.value=d.repo_url||''; await importRepository() }
function newConversation(){ sessionId.value=null; messages.value=[] }
function normalizeHistoryMessage(row){
  const rawMeta=row.role==='assistant'&&row.metadata_json&&typeof row.metadata_json==='object'?row.metadata_json:null
  const meta=rawMeta?{
    ...rawMeta,
    used_tools:Array.isArray(rawMeta.used_tools)?rawMeta.used_tools:[],
    sources:Array.isArray(rawMeta.sources)?rawMeta.sources:[],
  }:null
  return {role:row.role,content:row.content||'',meta,tools:meta?.used_tools||[],stages:[]}
}
async function openSession(){
  if(!sessionId.value){ messages.value=[]; return }
  const selectedId=Number(sessionId.value)
  if(!Number.isInteger(selectedId)){ newConversation(); return }
  try{
    const response=await fetch(`${API}/sessions/${selectedId}/messages`)
    if(!response.ok) throw new Error('历史对话加载失败')
    const rows=await response.json()
    messages.value=Array.isArray(rows)?rows.map(normalizeHistoryMessage):[]
    scrollToLatest(true)
  }catch(error){
    messages.value=[]
    alert(error.message||'历史对话加载失败')
  }
}
async function deleteConversation(){ if(!sessionId.value||!confirm('删除当前对话记录？此操作不可撤销。')) return; const r=await fetch(`${API}/sessions/${sessionId.value}`,{method:'DELETE'}); if(!r.ok){ const d=await r.json(); alert(d.detail||'删除失败'); return } newConversation(); await loadSessions() }
async function removeDoc(id){ if(!confirm('删除这份文档？')) return; await fetch(`${API}/documents/${id}`,{method:'DELETE'}); loadDocs() }
async function upload(){ const file = fileInput.value?.files?.[0]; if(!file) return; const fd = new FormData(); fd.append('file', file); fd.append('project_id',projectId.value); const r=await fetch(`${API}/documents/upload`,{method:'POST',body:fd}); const d=await r.json(); alert(r.ok?`已索引 ${d.chunk_count} 个片段`:d.detail); loadDocs() }
async function ask(){
  if(!question.value.trim()||loading.value) return
  const q=question.value
  question.value=''
  messages.value.push({role:'user',content:q})
  const reply=reactive({role:'assistant',content:'',meta:null,tools:[],stages:[]})
  messages.value.push(reply)
  scrollToLatest(true)
  loading.value=true
  try{
    const response=await fetch(`${API}/chat/stream`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,project_id:projectId.value,session_id:sessionId.value,reasoning_effort:reasoningEffort.value})})
    if(!response.ok||!response.body) throw new Error('请求失败')
    const reader=response.body.getReader(), decoder=new TextDecoder('utf-8')
    let buffer=''
    while(true){
      const {value,done}=await reader.read()
      if(done) break
      buffer+=decoder.decode(value,{stream:true})
      const blocks=buffer.split('\n\n')
      buffer=blocks.pop()||''
      for(const block of blocks){
        const event=block.match(/^event: (.+)$/m)?.[1]
        const raw=block.match(/^data: (.+)$/m)?.[1]
        if(!event||!raw) continue
        const data=JSON.parse(raw)
        if(event==='status'&&data.session_id) sessionId.value=data.session_id
        if(event==='stage'){
          const index=reply.stages.findIndex(stage=>stage.key===data.key)
          if(index>=0) reply.stages[index]=data
          else reply.stages.push(data)
          if(data.tool&&!reply.tools.includes(data.tool)) reply.tools.push(data.tool)
          scrollToLatest()
        }
        if(event==='delta'){ reply.content+=data.content; scrollToLatest() }
        if(event==='tool') reply.tools.push(data.tool)
        if(event==='answer'){ reply.meta=data; sessionId.value=data.session_id||sessionId.value; reply.content=data.answer; scrollToLatest(); loadSessions() }
        if(event==='error') throw new Error(data.message||'请求失败')
      }
    }
  }catch(error){ reply.content='## 请求失败\n无法连接后端服务，请确认 API 已启动后重试。' }
  finally{ loading.value=false }
}
function askExample(text){ question.value=text }
onMounted(async()=>{ sidebarWidth.value=Math.min(520,Math.max(260,Number(localStorage.getItem('atlas-sidebar-width'))||330)); await Promise.all([loadProjects(),loadSystemStatus()]); syncProjectForm(); await Promise.all([loadDocs(),loadSessions()]); projectPoller=setInterval(async()=>{ if(isImporting()){ await loadProjects(); syncProjectForm(); if(!isImporting()) await loadDocs() } },1200) })
onBeforeUnmount(()=>{ clearInterval(projectPoller); if(scrollFrame) cancelAnimationFrame(scrollFrame); if(stopResize) stopResize() })
</script>
<template>
  <main class="shell">
    <header><div><span class="eyebrow">PROJECT CONTEXT WORKSPACE</span><h1>Project <em>Atlas</em></h1><p>帮助开发者更快理解陌生代码库</p></div><div class="header-actions"><select v-model.number="projectId" @change="changeProject"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select><button v-if="activeProject()?.repo_url&&!isImporting()" class="sync" @click="importRepository">重新分析</button><button v-if="activeProject()" class="danger-action" :disabled="isImporting()" title="删除当前工作区" @click="deleteProject">删除工作区</button><select v-model="reasoningEffort" title="推理强度"><option value="auto">自动推理</option><option value="none">无推理</option><option value="minimal">最小</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">很高</option><option value="max">最大</option></select><button class="secondary-action" :disabled="testingModel||!systemStatus.llm_configured" @click="testModel">{{ testingModel?'测试中…':'测试模型' }}</button><span :title="systemStatus.llm_message" :class="['model-status',systemStatus.llm_reachable===true?'connected':'fallback']">{{ systemStatus.llm_reachable===true?`● ${systemStatus.llm_model}`:systemStatus.llm_reachable===false?'○ 连接失败':systemStatus.llm_configured?'○ 待测试':'○ 本地模式' }}</span><span class="status">● API READY</span></div></header>
    <section ref="gridEl" class="grid" :style="{'--sidebar-width':`${sidebarWidth}px`}">
      <aside class="panel docs"><div class="panel-title"><h2>项目资料</h2><span>{{ docs.length }} docs</span></div><div class="repo-summary"><strong>{{ activeProject()?.repo_status==='ready'?'仓库已建立索引':isImporting()?'正在导入并分析仓库':'仓库尚未分析' }}</strong><template v-if="isImporting()"><div class="progress-track"><span :style="{width:`${activeProject()?.repo_progress||0}%`}"></span></div><small>{{ activeProject()?.repo_stage }} · {{ activeProject()?.repo_progress||0 }}%</small></template><small v-else-if="activeProject()?.repo_status==='ready'">{{ activeProject()?.repo_indexed_files }} 个文件 · {{ activeProject()?.repo_last_commit?.slice(0,7) }}</small><small v-else-if="activeProject()?.repo_error" class="repo-error">{{ activeProject()?.repo_error }}</small><div v-if="!activeProject()?.repo_url&&!isImporting()" class="repo-url"><input v-model="repositoryUrl" placeholder="https://github.com/owner/repo"/><button :disabled="!repositoryUrl.trim()" @click="saveRepository">保存</button></div></div><details class="workspace-setup"><summary>管理当前 Workspace</summary><input v-model="editProject.name" placeholder="项目名称"/><input v-model="editProject.description" placeholder="项目说明"/><input v-model="editProject.repo_url" placeholder="公开 GitHub 仓库地址"/><small v-if="activeProject()?.repo_local_path" class="local-path" :title="activeProject().repo_local_path">{{ activeProject().repo_local_path }}</small><button :disabled="isImporting()" @click="updateProject">保存修改</button></details><details class="workspace-setup"><summary>新建项目 Workspace</summary><input v-model="newProject.name" placeholder="项目名称"/><input v-model="newProject.repo_url" placeholder="公开 GitHub 仓库地址（填写后自动导入）"/><button @click="createProject">创建并分析</button></details><label class="upload"><input ref="fileInput" type="file" @change="upload" accept=".pdf,.md,.txt,.json"/><strong>＋ 添加项目资料</strong><small>README / 架构文档 / Runbook</small></label><div class="document-list"><details v-for="group in documentGroups" :key="`${projectId}-${group.key}`" class="document-group" :open="group.open"><summary><span>{{ group.label }}</span><b>{{ group.items.length }}</b></summary><div v-for="doc in group.items" :key="doc.id" class="doc"><span class="dot"></span><div><b :title="doc.name">{{ doc.name }}</b><small>{{ doc.source_type }} · {{ doc.chunk_count }} chunks</small></div><button class="trash" title="删除文档" @click.prevent="removeDoc(doc.id)">×</button></div></details><div v-if="!docs.length" class="empty">先添加一个项目文档</div></div></aside>
      <div class="resize-handle" role="separator" aria-label="调整资料栏宽度" aria-orientation="vertical" tabindex="0" title="拖动调整资料栏宽度，双击恢复" @pointerdown="startResize" @dblclick="resetSidebar" @keydown="resizeWithKeyboard"></div>
      <section class="panel chat"><div class="panel-title"><div><h2>Atlas Assistant</h2><small>项目上下文 + RAG + Agent 工具</small></div><div class="session-actions"><select v-model.number="sessionId" title="历史会话" @change="openSession"><option :value="null">新对话</option><option v-for="session in sessions" :key="session.id" :value="session.id">{{ session.title }}</option></select><button title="开始新对话" @click="newConversation">＋</button><button v-if="sessionId" class="delete-session" title="删除当前对话" @click="deleteConversation">×</button></div></div><div ref="messagesEl" class="messages" @scroll="handleMessagesScroll"><div v-if="!messages.length" class="welcome"><div class="orb">✦</div><h3>快速理解这个项目</h3><p>选择一个真实场景开始：</p><div class="examples"><button @click="askExample('总结这个仓库的技术栈和主要模块')">仓库概览</button><button @click="askExample('项目如何启动？')">项目启动</button><button @click="askExample('新成员应该先阅读哪些文件？')">新人上手</button></div></div><TransitionGroup name="message"><div v-for="(m,i) in messages" :key="i" :class="['bubble',m.role]"><span>{{ m.role==='user'?'你':'Atlas' }}</span><details v-if="m.role==='assistant'&&m.meta&&m.stages?.length" class="activity"><summary>查看执行过程</summary><div v-for="stage in m.stages" :key="stage.key" class="activity-step"><i>✓</i><div><b>{{ stage.label }}</b><small>{{ stage.detail }}</small></div></div></details><div v-if="m.role==='assistant'" class="markdown-body" v-html="renderMarkdown(m.content)"></div><p v-else>{{ m.content }}</p><small v-if="m.role==='assistant'&&m.meta">{{ m.meta.answer_mode==='model'?'模型回答':m.meta.answer_mode==='structured'?'工具结果':'本地回退' }} · 工具：{{ m.meta.used_tools?.join(' → ') || '无' }} · {{ m.meta.confidence||'未知' }}<br/>来源：{{ m.meta.sources?.map(s=>s.document_name).join('、') || '无' }}</small></div></TransitionGroup><div v-if="loading&&!activeStage" class="typing"><i></i><i></i><i></i><span>Atlas 正在准备</span></div></div><div v-if="loading" class="generation-status"><i></i><div><b>{{ activeStage?.label||'正在准备回答' }}</b><small>{{ activeStage?.detail||'正在建立流式连接' }}</small></div><span>{{ activeReply?.stages?.length||0 }} 步</span></div><form @submit.prevent="ask"><input v-model="question" placeholder="输入问题，例如：这个仓库的主要模块是什么？"/><button>发送 ↗</button></form></section>
    </section>
  </main>
</template>
