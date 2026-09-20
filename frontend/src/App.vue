<script setup>
import { onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
const API = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api'
const projects = ref([]), projectId = ref(1), docs = ref([]), systemStatus = ref({llm_configured:false,llm_reachable:false,llm_model:null,llm_message:''}), question = ref(''), messages = ref([]), loading = ref(false), syncing = ref(false), importing = ref(false), fileInput = ref(null), newProject = ref({name:'',repo_url:''}), repositoryUrl = ref('')
const activeProject = ()=>projects.value.find(project=>project.id===projectId.value)
function renderMarkdown(text){ return DOMPurify.sanitize(marked.parse(text || '')) }
async function loadProjects(){ projects.value = await fetch(`${API}/projects`).then(r=>r.json()); if(projects.value.length && !projects.value.some(p=>p.id===projectId.value)) projectId.value=projects.value[0].id }
async function loadDocs(){ docs.value = await fetch(`${API}/documents?project_id=${projectId.value}`).then(r=>r.json()) }
async function loadSystemStatus(){ systemStatus.value = await fetch(`${API}/system/status`).then(r=>r.json()) }
async function changeProject(){ messages.value=[]; repositoryUrl.value=activeProject()?.repo_url||''; await loadDocs() }
async function createProject(){ const name=newProject.value.name.trim(); if(!name) return; const slug=`${name.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g,'-')}-${Date.now().toString().slice(-5)}`; const r=await fetch(`${API}/projects`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,slug,repo_url:newProject.value.repo_url.trim()||null})}); const d=await r.json(); if(!r.ok){alert(d.detail);return} newProject.value={name:'',repo_url:''}; await loadProjects(); projectId.value=d.id; await changeProject() }
async function syncContext(){ syncing.value=true; const r=await fetch(`${API}/projects/${projectId.value}/sync-context`,{method:'POST'}); const d=await r.json(); alert(r.ok?`已导入 ${d.indexed} 项，跳过 ${d.skipped} 项`:d.detail); syncing.value=false; loadDocs() }
async function importRepository(){ importing.value=true; const r=await fetch(`${API}/projects/${projectId.value}/import-repository`,{method:'POST'}); const d=await r.json(); alert(r.ok?`仓库分析完成：索引 ${d.indexed_files} 个文件，当前提交 ${d.commit.slice(0,7)}`:d.detail); importing.value=false; await loadProjects(); await loadDocs() }
async function saveRepository(){ const repo_url=repositoryUrl.value.trim(); if(!repo_url) return; const r=await fetch(`${API}/projects/${projectId.value}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url})}); const d=await r.json(); if(!r.ok){alert(d.detail);return} await loadProjects(); repositoryUrl.value=d.repo_url||'' }
async function removeDoc(id){ if(!confirm('删除这份文档？')) return; await fetch(`${API}/documents/${id}`,{method:'DELETE'}); loadDocs() }
async function upload(){ const file = fileInput.value?.files?.[0]; if(!file) return; const fd = new FormData(); fd.append('file', file); fd.append('project_id',projectId.value); const r=await fetch(`${API}/documents/upload`,{method:'POST',body:fd}); const d=await r.json(); alert(r.ok?`已索引 ${d.chunk_count} 个片段`:d.detail); loadDocs() }
async function ask(){
  if(!question.value.trim()||loading.value) return
  const q=question.value
  question.value=''
  messages.value.push({role:'user',content:q})
  const reply={role:'assistant',content:'',meta:null,tools:[]}
  messages.value.push(reply)
  loading.value=true
  try{
    const response=await fetch(`${API}/chat/stream`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,project_id:projectId.value})})
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
        if(event==='delta') reply.content+=data.content
        if(event==='tool') reply.tools.push(data.tool)
        if(event==='answer'){ reply.meta=data; if(!reply.content) reply.content=data.answer }
      }
    }
  }catch(error){ reply.content='## 请求失败\n无法连接后端服务，请确认 API 已启动后重试。' }
  finally{ loading.value=false }
}
function askExample(text){ question.value=text }
onMounted(async()=>{ await Promise.all([loadProjects(),loadSystemStatus()]); repositoryUrl.value=activeProject()?.repo_url||''; await loadDocs() })
</script>
<template>
  <main class="shell">
    <header><div><span class="eyebrow">PROJECT CONTEXT WORKSPACE</span><h1>Project <em>Atlas</em></h1><p>帮助开发者更快理解陌生代码库</p></div><div class="header-actions"><select v-model.number="projectId" @change="changeProject"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select><button v-if="activeProject()?.repo_url" class="secondary-action" :disabled="syncing||importing" @click="syncContext">{{ syncing?'同步中…':'同步动态' }}</button><button v-if="activeProject()?.repo_url" class="sync" :disabled="syncing||importing" @click="importRepository">{{ importing?'分析中…':'分析仓库' }}</button><span :title="systemStatus.llm_message" :class="['model-status',systemStatus.llm_reachable?'connected':'fallback']">{{ systemStatus.llm_reachable?`● ${systemStatus.llm_model}`:systemStatus.llm_configured?'○ 模型连接失败':'○ 本地模式' }}</span><span class="status">● API READY</span></div></header>
    <section class="grid">
      <aside class="panel docs"><div class="panel-title"><h2>项目资料</h2><span>{{ docs.length }} docs</span></div><div class="repo-summary"><strong>{{ activeProject()?.repo_status==='ready'?'仓库已建立索引':'仓库尚未分析' }}</strong><small v-if="activeProject()?.repo_status==='ready'">{{ activeProject()?.repo_indexed_files }} 个文件 · {{ activeProject()?.repo_last_commit?.slice(0,7) }}</small><div v-else class="repo-url"><input v-model="repositoryUrl" placeholder="https://github.com/owner/repo"/><button :disabled="!repositoryUrl.trim()" @click="saveRepository">保存</button></div></div><details class="workspace-setup"><summary>新建项目 Workspace</summary><input v-model="newProject.name" placeholder="项目名称"/><input v-model="newProject.repo_url" placeholder="公开 GitHub 仓库地址（可选）"/><button @click="createProject">创建项目</button></details><label class="upload"><input ref="fileInput" type="file" @change="upload" accept=".pdf,.md,.txt,.json"/><strong>＋ 添加项目资料</strong><small>README / 架构文档 / Runbook</small></label><div v-for="doc in docs" :key="doc.id" class="doc"><span class="dot"></span><div><b :title="doc.name">{{ doc.name }}</b><small>{{ doc.source_type }} · {{ doc.chunk_count }} chunks</small></div><button class="trash" @click="removeDoc(doc.id)">×</button></div><div v-if="!docs.length" class="empty">先添加一个项目文档</div></aside>
      <section class="panel chat"><div class="panel-title"><div><h2>Atlas Assistant</h2><small>项目上下文 + RAG + Agent 工具</small></div><span class="tag">PROJECT WORKSPACE</span></div><div class="messages"><div v-if="!messages.length" class="welcome"><div class="orb">✦</div><h3>快速理解这个项目</h3><p>选择一个真实场景开始：</p><div class="examples"><button @click="askExample('总结这个仓库的技术栈和主要模块')">仓库概览</button><button @click="askExample('项目如何启动？')">项目启动</button><button @click="askExample('新成员应该先阅读哪些文件？')">新人上手</button></div></div><div v-for="(m,i) in messages" :key="i" :class="['bubble',m.role]"><span>{{ m.role==='user'?'你':'Atlas' }}</span><div v-if="m.role==='assistant'" class="markdown-body" v-html="renderMarkdown(m.content)"></div><p v-else>{{ m.content }}</p><small v-if="m.tools?.length&&!m.meta">正在调用：{{ m.tools.join(' → ') }}</small><small v-if="m.meta">工具：{{ m.meta.used_tools.join(' → ') }} · {{ m.meta.confidence }}<br/>来源：{{ m.meta.sources.map(s=>s.document_name).join('、') || '无' }}</small></div><div v-if="loading" class="typing">Atlas 正在检索项目上下文…</div></div><form @submit.prevent="ask"><input v-model="question" placeholder="输入问题，例如：这个仓库的主要模块是什么？"/><button>发送 ↗</button></form></section>
    </section>
  </main>
</template>
