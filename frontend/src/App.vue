<script setup>
import { onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
const API = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api'
const docs = ref([]), question = ref(''), messages = ref([]), loading = ref(false), fileInput = ref(null)
function renderMarkdown(text){ return DOMPurify.sanitize(marked.parse(text || '')) }
async function loadDocs(){ docs.value = await fetch(`${API}/documents?project_id=1`).then(r=>r.json()) }
async function removeDoc(id){ if(!confirm('删除这份文档？')) return; await fetch(`${API}/documents/${id}`,{method:'DELETE'}); loadDocs() }
async function upload(){ const file = fileInput.value?.files?.[0]; if(!file) return; const fd = new FormData(); fd.append('file', file); const r=await fetch(`${API}/documents/upload`,{method:'POST',body:fd}); const d=await r.json(); alert(r.ok?`已索引 ${d.chunk_count} 个片段`:d.detail); loadDocs() }
async function ask(){ if(!question.value.trim()||loading.value) return; const q=question.value; question.value=''; messages.value.push({role:'user',content:q}); loading.value=true; const r=await fetch(`${API}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})}); const d=await r.json(); messages.value.push({role:'assistant',content:d.answer,meta:d}); loading.value=false }
function askExample(text){ question.value=text }
onMounted(loadDocs)
</script>
<template>
  <main class="shell">
    <header><div><span class="eyebrow">PROJECT CONTEXT WORKSPACE</span><h1>Project <em>Atlas</em></h1><p>帮助开发者更快理解陌生代码库</p></div><span class="status">● API READY</span></header>
    <section class="grid">
      <aside class="panel docs"><div class="panel-title"><h2>项目资料</h2><span>{{ docs.length }} docs</span></div><label class="upload"><input ref="fileInput" type="file" @change="upload" accept=".pdf,.md,.txt,.json"/><strong>＋ 添加项目资料</strong><small>README / 架构文档 / Runbook</small></label><div v-for="doc in docs" :key="doc.id" class="doc"><span class="dot"></span><div><b>{{ doc.name }}</b><small>{{ doc.status }} · {{ doc.chunk_count }} chunks</small></div><button class="trash" @click="removeDoc(doc.id)">×</button></div><div v-if="!docs.length" class="empty">先添加一个项目文档</div></aside>
      <section class="panel chat"><div class="panel-title"><div><h2>Atlas Assistant</h2><small>项目上下文 + RAG + Agent 工具</small></div><span class="tag">PROJECT WORKSPACE</span></div><div class="messages"><div v-if="!messages.length" class="welcome"><div class="orb">✦</div><h3>快速理解这个项目</h3><p>选择一个真实场景开始：</p><div class="examples"><button @click="askExample('项目如何启动？')">项目启动</button><button @click="askExample('新成员应该先阅读哪些文档？')">新人上手</button><button @click="askExample('支付服务 503 怎么排查？')">排查 503</button></div></div><div v-for="(m,i) in messages" :key="i" :class="['bubble',m.role]"><span>{{ m.role==='user'?'你':'Atlas' }}</span><div v-if="m.role==='assistant'" class="markdown-body" v-html="renderMarkdown(m.content)"></div><p v-else>{{ m.content }}</p><small v-if="m.meta">工具：{{ m.meta.used_tools.join(' → ') }} · {{ m.meta.confidence }}<br/>来源：{{ m.meta.sources.map(s=>s.document_name).join('、') || '无' }}</small></div><div v-if="loading" class="typing">Atlas 正在检索项目上下文…</div></div><form @submit.prevent="ask"><input v-model="question" placeholder="输入问题，例如：新成员应该先阅读哪些文档？"/><button>发送 ↗</button></form></section>
    </section>
  </main>
</template>
