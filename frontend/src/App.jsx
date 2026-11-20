import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertCircle, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, Bot,
  Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleHelp,
  Clock3, CloudUpload, FileText, Filter, Gauge, Headphones, LayoutDashboard,
  LifeBuoy, LoaderCircle, Menu, Plus, RefreshCw, Search, Send, Settings,
  ShieldCheck, Sparkles, Ticket, Users, X, Zap
} from 'lucide-react';

const API = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const USE_MOCKS = false; // Change to false when the Milestone 2 backend is available.
const MOCK_ARTICLES = [
 {slug:'vpn-timeout',title:'VPN Connection Timeout',category:'VPN',score:0.94,content:'1. Check your internet connection.\n2. Restart the VPN client.\n3. Sign in again using your organization credentials.\n4. Contact IT if the timeout continues.'},
 {slug:'wifi-connectivity',title:'Troubleshoot Wi-Fi Connectivity',category:'Network',score:0.87,content:'1. Confirm Wi-Fi is enabled.\n2. Reconnect to the network.\n3. Restart your device if needed.'},
 {slug:'email-sync',title:'Resolve Email Synchronization',category:'Email',score:0.82,content:'1. Check your internet connection.\n2. Restart the email application.\n3. Verify account settings.'}
];
const MOCK_TICKET = {ticket_id:1,ticket_code:'SP-1001',subject:'VPN keeps timing out',description:'My VPN connection times out whenever I try to connect from home.',requester_email:'alex@company.com',department:'IT',category:'VPN',category_confidence:0.94,severity:'High',severity_confidence:0.91,priority:'P2',status:'Classified',source:'web',processing_ms:142,created_at:new Date().toISOString()};
const MOCK_RESPONSE = {response_text:'Hello! Based on article VPN Connection Timeout, please try these steps:\n1. Check your internet connection.\n2. Restart the VPN client.\n3. Sign in again using your organization credentials.\n4. Contact IT if the timeout continues.\n\nSource: VPN Connection Timeout',steps:['Check your internet connection.','Restart the VPN client.','Sign in again using your organization credentials.','Contact IT if the timeout continues.'],sources:['VPN Connection Timeout'],articles:[MOCK_ARTICLES[0]],confidence:0.92,mode:'template',needs_human_review:false,trace:[{name:'Analyze ticket',time_ms:12},{name:'Retrieve articles',time_ms:86},{name:'Add context',time_ms:9},{name:'Generate response',time_ms:35}],response_ms:142};

const CATEGORIES = ['Network', 'VPN', 'Software', 'Hardware', 'Password Reset', 'Email', 'Security'];
const STATUSES = ['Open', 'Classified', 'In Progress', 'Resolved', 'Closed'];
const NEXT_STATUS = { Open: 'Classified', Classified: 'In Progress', 'In Progress': 'Resolved', Resolved: 'Closed' };
const initialForm = { name: '', email: '', department: 'IT', subject: '', description: '' };

async function api(path, options = {}) {
  if (USE_MOCKS) {
    const method = options.method || 'GET';
    if (path === '/stats') return {total_tickets:1,tickets_today:1,avg_processing_ms:142,by_status:{Classified:1},by_severity:{High:1},by_category:{VPN:1},classifier_in_use:'Mock classifier'};
    if (path.startsWith('/tickets?')) return [MOCK_TICKET];
    if (path === '/tickets' && method === 'POST') return {...MOCK_TICKET,ticket_id:Date.now(),ticket_code:'SP-DEMO'};
    if (/^\/tickets\/\d+$/.test(path)) return MOCK_TICKET;
    if (/^\/tickets\/\d+\/history$/.test(path)) return [{log_id:1,action:'Ticket classified and resolution generated',performed_by:'SupportPilot',timestamp:new Date().toISOString()}];
    if (/^\/tickets\/\d+\/(response|resolve)$/.test(path)) return MOCK_RESPONSE;
    if (path === '/rag/stats') return {article_count:60,responses_generated:128,average_confidence:0.89,review_percentage:12.5,average_response_time:184};
    if (path.startsWith('/kb/search')) { const q = new URLSearchParams(path.split('?')[1] || '').get('query')?.toLowerCase() || ''; return MOCK_ARTICLES.filter(a => !q || `${a.title} ${a.category} ${a.content}`.toLowerCase().includes(q)); }
    if (path.startsWith('/kb/articles')) return MOCK_ARTICLES;
    if (path.includes('/status') && method === 'PATCH') return {...MOCK_TICKET,status:'In Progress'};
    return {};
  }
  const response = await fetch(`${API}${path}`, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(typeof payload === 'string' ? payload : payload.detail || JSON.stringify(payload));
  return payload;
}
function dateText(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function shortDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function statusClass(value = '') { return `status-${value.toLowerCase().replaceAll(' ', '-')}`; }
function severityClass(value = '') { return `severity-${value.toLowerCase()}`; }
function confidence(value) { return value == null ? '—' : `${Math.round(value * 100)}%`; }
function Empty({ title, detail }) { return <div className="empty-state"><div className="empty-icon"><FileText size={22}/></div><b>{title}</b><span>{detail}</span></div>; }
function Toast({ toast, onClose }) {
  if (!toast) return null;
  return <div className={`toast ${toast.type}`} role="status"><span className="toast-icon">{toast.type === 'error' ? <AlertCircle size={18}/> : <CheckCircle2 size={18}/>}</span><span>{toast.message}</span><button className="icon-button" onClick={onClose} aria-label="Dismiss"><X size={16}/></button></div>;
}
function App() {
  const [page, setPage] = useState('Overview');
  const [stats, setStats] = useState(null);
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState('');
  const [toast, setToast] = useState(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All statuses');
  const [categoryFilter, setCategoryFilter] = useState('All categories');
  const [severityFilter, setSeverityFilter] = useState('All severities');
  const [showNew, setShowNew] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);
  const [bulkFile, setBulkFile] = useState(null);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [kbArticles, setKbArticles] = useState([]);
  const [kbQuery, setKbQuery] = useState('');
  const [kbCategory, setKbCategory] = useState('All categories');
  const [kbSelected, setKbSelected] = useState(null);
  const [kbLoading, setKbLoading] = useState(false);
  const [ragStats, setRagStats] = useState(null);
  const [resolution, setResolution] = useState(null);
  const [resolutionLoading, setResolutionLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, t] = await Promise.all([api('/stats'), api('/tickets?limit=500')]);
      setStats(s); setTickets(t); setApiError('');
    } catch (err) { setApiError(err.message || 'Could not connect to the SupportPilot API.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (page === 'Knowledge base') loadKnowledge('', 'All categories'); if (page === 'RAG metrics') loadRagStats(); }, [page]);
  useEffect(() => { if (!toast) return; const id = setTimeout(() => setToast(null), 4500); return () => clearTimeout(id); }, [toast]);

  const visibleTickets = useMemo(() => tickets.filter(t => {
    const text = `${t.ticket_code || ''} ${t.subject || ''} ${t.description || ''} ${t.requester_email || ''} ${t.category || ''}`.toLowerCase();
    return text.includes(search.toLowerCase()) && (statusFilter === 'All statuses' || t.status === statusFilter) && (categoryFilter === 'All categories' || t.category === categoryFilter) && (severityFilter === 'All severities' || t.severity === severityFilter);
  }), [tickets, search, statusFilter, categoryFilter, severityFilter]);

  const navigate = (next) => { setPage(next); setMobileNav(false); if (next === 'New ticket') { setShowNew(true); setPage('Tickets'); } };
  const openTicket = async (ticket) => {
    setSelected(ticket); setHistory([]); setHistoryLoading(true);
    try { const [fresh, logs, answer] = await Promise.all([api(`/tickets/${ticket.ticket_id}`), api(`/tickets/${ticket.ticket_id}/history`), api(`/tickets/${ticket.ticket_id}/response`).catch(() => null)]); setSelected(fresh); setHistory(logs); setResolution(answer); }
    catch (err) { setToast({ type: 'error', message: err.message }); }
    finally { setHistoryLoading(false); }
  };
  const submitTicket = async (e) => {
    e.preventDefault(); setSubmitting(true);
    try {
      const created = await api('/tickets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...form, source: 'web', subject: form.subject.trim() || null, name: form.name.trim() || null }) });
      setToast({ type: 'success', message: `Ticket ${created.ticket_code || `#${created.ticket_id}`} submitted successfully.` });
      setForm(initialForm); setShowNew(false); await refresh(); await openTicket(created);
    } catch (err) { setToast({ type: 'error', message: err.message || 'Ticket could not be submitted.' }); }
    finally { setSubmitting(false); }
  };
  const changeStatus = async () => {
    if (!selected || !NEXT_STATUS[selected.status]) return;
    setStatusSaving(true);
    try {
      const updated = await api(`/tickets/${selected.ticket_id}/status`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: NEXT_STATUS[selected.status], performed_by: 'Support team' }) });
      setSelected(updated); setToast({ type: 'success', message: `Ticket status updated to ${updated.status}.` }); await refresh();
      const logs = await api(`/tickets/${updated.ticket_id}/history`); setHistory(logs);
    } catch (err) { setToast({ type: 'error', message: err.message }); }
    finally { setStatusSaving(false); }
  };
  const uploadBulk = async (e) => {
    e.preventDefault(); if (!bulkFile) return;
    setBulkLoading(true);
    try {
      const body = new FormData(); body.append('file', bulkFile);
      const result = await api('/tickets/bulk', { method: 'POST', body });
      setToast({ type: result.failed ? 'error' : 'success', message: `Upload complete: ${result.created} created, ${result.failed} failed.` });
      setShowBulk(false); setBulkFile(null); await refresh();
    } catch (err) { setToast({ type: 'error', message: err.message }); }
    finally { setBulkLoading(false); }
  };


  const loadKnowledge = async (query = kbQuery, category = kbCategory) => {
    setKbLoading(true);
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set('q', query.trim());
      if (category !== 'All categories') params.set('category', category);
      const result = await api(query.trim() ? `/kb/search?${params}` : '/kb/articles?limit=500&offset=0');
      const list = Array.isArray(result) ? result : (result.results || result.articles || result.items || []);
      const filtered = category === 'All categories' ? list : list.filter(a => a.category === category);
      setKbArticles(filtered); if (filtered.length > 0) {
  const firstArticle = await api(`/kb/articles/${filtered[0].article_id}`);
  setKbSelected(firstArticle);
} else {
  setKbSelected(null);
}
    } catch (err) { setToast({type:'error',message:err.message || 'Could not load knowledge base.'}); }
    finally { setKbLoading(false); }
  };
  const loadRagStats = async () => { try { setRagStats(await api('/rag/stats')); } catch (err) { setToast({type:'error',message:err.message}); } };
  const regenerateResolution = async () => {
    if (!selected) return;
    setResolutionLoading(true);
    try { const result = await api(`/tickets/${selected.ticket_id}/resolve`,{method:'POST'}); setResolution(result); setToast({type:'success',message:'Resolution regenerated.'}); }
    catch (err) { setToast({type:'error',message:err.message || 'Could not regenerate resolution.'}); }
    finally { setResolutionLoading(false); }
  };
  const copyResolution = async () => {
    const text = resolution?.response_text || (resolution?.steps || []).join('\n');
    try { await navigator.clipboard.writeText(text); setToast({type:'success',message:'Reply copied to clipboard.'}); }
    catch { setToast({type:'error',message:'Clipboard access unavailable in this browser.'}); }
  };
  const total = stats?.total_tickets ?? tickets.length;
  const openCount = (stats?.by_status?.Open || 0) + (stats?.by_status?.Classified || 0) + (stats?.by_status?.['In Progress'] || 0);
  const criticalCount = (stats?.by_severity?.Critical || 0) + (stats?.by_severity?.High || 0);
  const averageMs = stats?.avg_processing_ms;
  const navItems = [
    { label: 'WORKSPACE', items: [{ name: 'Overview', icon: LayoutDashboard }, { name: 'Tickets', icon: Ticket }, { name: 'Knowledge base', icon: FileText }, { name: 'RAG metrics', icon: Activity }] },
    { label: 'MANAGEMENT', items: [{ name: 'AI operations', icon: Bot }, { name: 'Analytics', icon: Activity }, { name: 'Team', icon: Users }] },
  ];

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Sparkles size={21}/></div><div><strong>SupportPilot</strong><small>AI SUPPORT PLATFORM</small></div><button className="mobile-close icon-button" onClick={() => setMobileNav(false)}><X size={18}/></button></div>
      <div className="workspace"><div className="workspace-avatar">SP</div><div className="workspace-copy"><b>Support workspace</b><span>IT Operations</span></div><ChevronDown size={15}/></div>
      <nav className="side-nav">{navItems.map(group => <div className="nav-group" key={group.label}><div className="nav-label">{group.label}</div>{group.items.map(item => <button key={item.name} className={`nav-item ${page === item.name ? 'active' : ''} ${['AI operations','Team'].includes(item.name) ? 'nav-planned' : ''}`} onClick={() => { if (['AI operations','Team'].includes(item.name)) { setToast({type:'error', message:`${item.name} is not available in the current backend yet.`}); return; } navigate(item.name); }}><item.icon size={18}/><span>{item.name}</span>{item.name === 'Tickets' && tickets.length > 0 && <span className="nav-count">{tickets.length}</span>}</button>)}</div>)}</nav>
      <div className="sidebar-bottom"><div className="help-card"><div className="help-icon"><LifeBuoy size={19}/></div><b>Need a hand?</b><p>Check your API connection and project setup.</p><button onClick={() => window.open(`${API}/docs`, '_blank', 'noopener,noreferrer')}>Open API docs <ArrowRight size={14}/></button></div><div className="user-profile"><div className="user-avatar">ST</div><div className="user-info"><b>Support Team</b><span>Administrator</span></div><Settings size={17}/></div></div>
    </aside>
    {mobileNav && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)}/>}
    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="mobile-menu icon-button" onClick={() => setMobileNav(true)}><Menu size={21}/></button><div className="breadcrumb">Workspace <ChevronRight size={14}/> <b>{page}</b></div></div><div className="topbar-actions"><div className={`connection-pill ${apiError ? 'offline' : 'online'}`}><span className="connection-dot"/>{apiError ? 'API disconnected' : 'API connected'}</div><button className="icon-button notification" title="Notifications" onClick={() => setToast({type:'success', message:'You are all caught up.'})}><Bell size={19}/><i/></button><div className="top-avatar">ST</div></div></header>
      <div className="page-content">
        {apiError && <div className="api-alert"><AlertCircle size={18}/><div><b>Backend connection unavailable</b><span>{apiError} Start FastAPI at {API} and refresh.</span></div><button className="outline-button compact" onClick={refresh}><RefreshCw size={14}/> Retry</button></div>}
        {page === 'Overview' && <>
          <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> YOUR SUPPORT COMMAND CENTER</div><h1>Good to see you, team <span className="wave">✦</span></h1><p>Here’s what’s happening across your support operations today.</p></div><div className="heading-actions"><button className="outline-button" onClick={() => setShowBulk(true)}><CloudUpload size={16}/> Import CSV</button><button className="primary-button" onClick={() => setShowNew(true)}><Plus size={17}/> Create ticket</button></div></section>
          <section className="metric-grid">
            <Metric title="Total tickets" value={total.toLocaleString()} sub="All submitted requests" icon={Ticket} tone="blue" trend="Live count"/>
            <Metric title="Needs attention" value={openCount.toLocaleString()} sub="Open, classified or in progress" icon={Clock3} tone="amber" trend={total ? `${Math.round(openCount / total * 100)}% of tickets` : 'No tickets yet'}/>
            <Metric title="High impact" value={criticalCount.toLocaleString()} sub="High + critical severity" icon={AlertCircle} tone="rose" trend="Priority review"/>
            <Metric title="Avg. AI classification" value={averageMs == null ? '—' : averageMs < 1000 ? `${Math.round(averageMs)} ms` : `${(averageMs / 1000).toFixed(2)} s`} sub="Classification processing time" icon={Zap} tone="violet" trend={stats?.classifier_in_use || 'Classifier'}/>
          </section>
          <section className="overview-grid"><div className="panel ticket-panel"><div className="panel-header"><div><h2>Recent tickets</h2><p>Latest requests from across your organization</p></div><button className="text-button" onClick={() => navigate('Tickets')}>View all <ArrowRight size={15}/></button></div><TicketTable tickets={tickets.slice(0, 6)} loading={loading} onOpen={openTicket}/></div>
            <div className="panel insights-panel"><div className="panel-header"><div><h2>Ticket insights</h2><p>Current workload breakdown</p></div><div className="panel-icon"><Activity size={17}/></div></div><Breakdown title="By status" data={stats?.by_status || {}} colors={['#6575e8','#35b7a0','#f3ad4f','#3f9e78','#a3adbf']}/><div className="panel-divider"/><Breakdown title="By severity" data={stats?.by_severity || {}} colors={['#40b7a4','#f0b44f','#f1845c','#d94c67']}/><div className="insight-foot"><ShieldCheck size={17}/><span>Classification data is supplied by the connected backend.</span></div></div></section>
          <section className="panel category-panel"><div className="panel-header"><div><h2>Category distribution</h2><p>Understand which areas generate the most support requests</p></div><span className="subtle-badge">{Object.keys(stats?.by_category || {}).length} categories</span></div><div className="category-grid">{CATEGORIES.map((cat, i) => { const count = stats?.by_category?.[cat] || 0; const max = Math.max(1, ...Object.values(stats?.by_category || {}).map(Number)); const Icon = [Activity, ShieldCheck, Settings, Gauge, CircleHelp, Send, AlertCircle][i]; return <button className="category-tile" key={cat} onClick={() => {setCategoryFilter(cat); setPage('Tickets');}}><div className={`category-icon cat-${i}`}><Icon size={17}/></div><div className="category-info"><b>{cat}</b><span>{count} tickets</span><div className="mini-track"><i style={{width:`${count/max*100}%`}}/></div></div><ArrowUpRight size={15} className="category-arrow"/></button>; })}</div></section>
          <section className="bottom-banner"><div className="banner-sparkle"><Sparkles size={22}/></div><div><b>AI ticket classification is ready</b><p>Submit a request to classify its category, severity and priority automatically.</p></div><button className="banner-button" onClick={() => setShowNew(true)}>Submit a ticket <ArrowRight size={15}/></button></section>
        </>}
        {page === 'Tickets' && <><section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> SUPPORT OPERATIONS</div><h1>Ticket management</h1><p>Review incoming requests, AI classifications, and ticket lifecycle progress.</p></div><div className="heading-actions"><button className="outline-button" onClick={() => setShowBulk(true)}><CloudUpload size={16}/> Import CSV</button><button className="primary-button" onClick={() => setShowNew(true)}><Plus size={17}/> Create ticket</button></div></section><section className="panel tickets-full"><div className="filters-row"><div className="search-box"><Search size={17}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tickets, email, category..."/><kbd>⌘ K</kbd></div><div className="filter-select"><Filter size={15}/><select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option>All statuses</option>{STATUSES.map(s => <option key={s}>{s}</option>)}</select></div><div className="filter-select"><select value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)}><option>All categories</option>{CATEGORIES.map(s => <option key={s}>{s}</option>)}</select></div><div className="filter-select"><select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}><option>All severities</option>{['Low','Medium','High','Critical'].map(s => <option key={s}>{s}</option>)}</select></div><button className="icon-button refresh-btn" onClick={refresh} title="Refresh tickets"><RefreshCw size={17}/></button></div><div className="results-label">Showing <b>{visibleTickets.length}</b> of <b>{tickets.length}</b> tickets</div><TicketTable tickets={visibleTickets} loading={loading} onOpen={openTicket}/></section></>}
        {page === 'Knowledge base' && <>
          <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> SUPPORT KNOWLEDGE</div><h1>Knowledge base</h1><p>Search approved troubleshooting articles and resolution guides.</p></div><button className="outline-button" onClick={() => loadKnowledge()}><RefreshCw size={15}/> Refresh</button></section>
          <section className="panel kb-panel"><div className="kb-toolbar"><div className="search-box"><Search size={17}/><input value={kbQuery} onChange={e=>setKbQuery(e.target.value)} onKeyDown={e=>e.key==='Enter'&&loadKnowledge(kbQuery,kbCategory)} placeholder="Search articles, keywords, or issue..."/></div><select value={kbCategory} onChange={e=>{setKbCategory(e.target.value);loadKnowledge(kbQuery,e.target.value);}}><option>All categories</option>{CATEGORIES.map(c=><option key={c}>{c}</option>)}</select><button className="primary-button" onClick={()=>loadKnowledge(kbQuery,kbCategory)}><Search size={15}/> Search</button></div>
          {kbLoading ? <div className="table-loading"><LoaderCircle className="spin" size={22}/> Loading knowledge articles...</div> : !kbArticles.length ? <Empty title="No matching article" detail="Try another search term or choose a different category."/> : <div className="kb-layout"><div className="kb-list">{kbArticles.map(a=><button key={a.article_id || a.slug || a.title} className={`kb-item ${kbSelected===a?'active':''}`} onClick={async () => {
  try {
    const article = await api(`/kb/articles/${a.article_id}`);
    setKbSelected(article);
  } catch (err) {
    setToast({ type: 'error', message: err.message || 'Could not load article.' });
  }
}}><b>{a.title}</b><span>{a.category}</span></button>)}</div><article className="kb-viewer">{kbSelected ? <><span className="category-pill">{kbSelected.category}</span><h2>{kbSelected.title}</h2><p className="kb-content">{kbSelected.content || kbSelected.body || 'Article content is not available.'}</p></> : <Empty title="Select an article" detail="Choose an article to read its instructions."/>}</article></div>}</section>
        </>}
        {page === 'RAG metrics' && <>
          <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> RETRIEVAL & GENERATION</div><h1>RAG performance</h1><p>Knowledge base coverage and AI resolution quality indicators.</p></div><button className="outline-button" onClick={loadRagStats}><RefreshCw size={15}/> Refresh metrics</button></section>
          {ragStats ? <section className="metric-grid rag-metric-grid">
           <Metric title="Knowledge articles" value={ragStats.kb_articles ?? ragStats.article_count ?? ragStats.articles ?? 0} sub="Indexed KB articles" icon={FileText} tone="blue"/>
            <Metric title="Responses generated" value={ragStats.responses_generated ?? 0} sub="Stored AI resolutions" icon={Bot} tone="teal"/>
            <Metric title="Average confidence" value={confidence(ragStats.average_confidence ?? ragStats.avg_confidence)} sub="Across generated responses" icon={Gauge} tone="violet"/>
            <Metric title="Needs human review" value={`${Number(ragStats.needs_human_review_pct ?? ragStats.review_percentage ?? ragStats.needs_review_percent ?? 0).toFixed(1)}%`} sub="Responses flagged for review" icon={AlertCircle} tone="amber"/>
            <Metric title="Average response time" value={`${Math.round(ragStats.average_response_time ?? ragStats.avg_response_ms ?? 0)} ms`} sub="Resolution generation latency" icon={Clock3} tone="rose"/>
          </section> : <div className="panel"><div className="table-loading"><LoaderCircle className="spin" size={22}/> Loading RAG metrics...</div></div>}
        </>}
        {page === 'Analytics' && <><section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> REPORTING & PERFORMANCE</div><h1>Support analytics</h1><p>Live ticket volume, classification breakdowns and workflow status.</p></div><button className="outline-button" onClick={refresh}><RefreshCw size={15}/> Refresh metrics</button></section><div className="metric-grid"><Metric title="Total tickets" value={total} sub="All recorded tickets" icon={Ticket} tone="blue"/><Metric title="Created today" value={stats?.tickets_today ?? 0} sub="Since today's UTC midnight" icon={ArrowUpRight} tone="teal"/><Metric title="High impact" value={criticalCount} sub="High + critical severity" icon={AlertCircle} tone="rose"/><Metric title="Avg. classification time" value={averageMs == null ? '—' : `${Math.round(averageMs)} ms`} sub="From backend stats" icon={Zap} tone="violet"/></div><div className="analytics-grid"><div className="panel"><div className="panel-header"><div><h2>Ticket status</h2><p>Lifecycle distribution</p></div></div><Breakdown title="" data={stats?.by_status || {}} colors={['#6575e8','#35b7a0','#f3ad4f','#3f9e78','#a3adbf']} large/></div><div className="panel"><div className="panel-header"><div><h2>Severity levels</h2><p>Tickets by impact</p></div></div><Breakdown title="" data={stats?.by_severity || {}} colors={['#40b7a4','#f0b44f','#f1845c','#d94c67']} large/></div><div className="panel analytics-wide"><div className="panel-header"><div><h2>Category volume</h2><p>Distribution across supported ticket categories</p></div></div><Breakdown title="" data={stats?.by_category || {}} colors={['#6575e8','#35b7a0','#f3ad4f','#3f9e78','#a3adbf','#b08ad9','#f1845c']} large/></div></div></>}
      </div>
      <footer className="app-footer"><span>© 2026 SupportPilot</span><span><span className={`footer-dot ${apiError ? 'red' : ''}`}/>{apiError ? 'Backend offline' : 'Connected to SupportPilot API'} <span className="footer-separator">·</span> Milestone 2: RAG resolution & knowledge base</span></footer>
    </main>
    {showNew && <div className="modal-backdrop" onMouseDown={e => {if(e.target === e.currentTarget) setShowNew(false);}}><div className="modal new-ticket-modal"><div className="modal-header"><div className="modal-heading-icon"><Plus size={20}/></div><div><h2>Create support ticket</h2><p>Submit an issue for automatic AI classification.</p></div><button className="icon-button" onClick={() => setShowNew(false)}><X size={19}/></button></div><form onSubmit={submitTicket} className="modal-form"><div className="form-grid"><label>Requester name <span className="optional">Optional</span><input value={form.name} onChange={e => setForm({...form,name:e.target.value})} placeholder="e.g. Alex Morgan"/></label><label>Email address <span className="required">*</span><input type="email" required value={form.email} onChange={e => setForm({...form,email:e.target.value})} placeholder="you@company.com"/></label><label>Department <span className="required">*</span><select value={form.department} onChange={e => setForm({...form,department:e.target.value})}>{['IT','Finance','Human Resources','Operations','Sales','Engineering','Other'].map(d => <option key={d}>{d}</option>)}</select></label><label>Subject <span className="optional">Optional</span><input value={form.subject} onChange={e => setForm({...form,subject:e.target.value})} placeholder="Short summary of the issue"/></label><label className="full-field">Describe the issue <span className="required">*</span><textarea required minLength={5} rows={5} value={form.description} onChange={e => setForm({...form,description:e.target.value})} placeholder="Tell us what happened, what you were trying to do, and any error messages..."/><small>At least 5 characters. The AI classifier uses this description to label the ticket.</small></label></div><div className="ai-note"><div><Sparkles size={18}/></div><span><b>AI-powered classification</b><small>Category, severity and priority will be assigned by your backend after submission.</small></span></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setShowNew(false)}>Cancel</button><button type="submit" className="primary-button" disabled={submitting}>{submitting ? <LoaderCircle className="spin" size={16}/> : <Send size={16}/>} {submitting ? 'Submitting...' : 'Submit ticket'}</button></div></form></div></div>}
    {showBulk && <div className="modal-backdrop" onMouseDown={e => {if(e.target === e.currentTarget) setShowBulk(false);}}><div className="modal bulk-modal"><div className="modal-header"><div className="modal-heading-icon"><CloudUpload size={20}/></div><div><h2>Import tickets from CSV</h2><p>Bulk-create tickets using the backend import endpoint.</p></div><button className="icon-button" onClick={() => setShowBulk(false)}><X size={19}/></button></div><form onSubmit={uploadBulk} className="modal-form"><div className="upload-drop"><CloudUpload size={28}/><b>Choose a CSV file</b><span>CSV file with a header row · Up to 5,000 rows</span><label className="file-pick">Browse files<input type="file" accept=".csv,text/csv" onChange={e => setBulkFile(e.target.files?.[0] || null)}/></label>{bulkFile && <div className="picked-file"><FileText size={16}/>{bulkFile.name}<span>{(bulkFile.size/1024).toFixed(1)} KB</span></div>}</div><div className="csv-help"><b>Required columns</b><code>description, email</code><b>Optional columns</b><code>subject, department, name</code><p>Tickets are created with source <code>api</code> and classified by the backend.</p></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setShowBulk(false)}>Cancel</button><button className="primary-button" type="submit" disabled={!bulkFile || bulkLoading}>{bulkLoading ? <LoaderCircle className="spin" size={16}/> : <CloudUpload size={16}/>} {bulkLoading ? 'Importing...' : 'Import tickets'}</button></div></form></div></div>}
    {selected && <div className="drawer-backdrop" onMouseDown={e => {if(e.target === e.currentTarget) setSelected(null);}}><aside className="ticket-drawer"><div className="drawer-header"><div><span className="drawer-kicker">TICKET DETAILS</span><h2>{selected.ticket_code || `Ticket #${selected.ticket_id}`}</h2></div><button className="icon-button" onClick={() => setSelected(null)}><X size={20}/></button></div><div className="drawer-scroll"><div className="drawer-title-row"><h3>{selected.subject || 'Support request'}</h3><span className={`status-badge ${statusClass(selected.status)}`}>{selected.status}</span></div><p className="drawer-description">{selected.description}</p><div className="requester-card"><div className="requester-avatar">{(selected.requester_email || 'U').slice(0,1).toUpperCase()}</div><div><b>{selected.requester_email || 'Unknown requester'}</b><span>{selected.department || 'IT'} department · Submitted {dateText(selected.created_at)}</span></div></div><div className="drawer-section"><div className="drawer-section-title"><h4>AI classification</h4><span><Sparkles size={14}/> Backend result</span></div><div className="classification-grid"><div className="classify-card"><span>Category</span><b>{selected.category || 'Unclassified'}</b><small>Confidence: {confidence(selected.category_confidence)}</small></div><div className="classify-card"><span>Severity</span><b><i className={`severity-dot ${severityClass(selected.severity)}`}/>{selected.severity || '—'}</b><small>Confidence: {confidence(selected.severity_confidence)}</small></div><div className="classify-card"><span>Priority</span><b className={`priority-text ${selected.priority === 'P1' ? 'p1' : ''}`}>{selected.priority || '—'}</b><small>Source: {selected.source || 'web'}</small></div><div className="classify-card"><span>Processing time</span><b>{selected.processing_ms == null ? '—' : `${selected.processing_ms.toFixed(2)} ms`}</b><small>Classifier execution</small></div></div></div><div className="drawer-section resolution-section"><div className="drawer-section-title"><h4>AI resolution</h4><span><Sparkles size={14}/> RAG pipeline</span></div>
          {resolutionLoading ? <div className="inline-loading"><LoaderCircle className="spin" size={17}/> Generating resolution...</div> : resolution ? <>
            <div className="rag-trace">{(resolution.trace || []).map((step,i)=><div className="rag-trace-step" key={step.name || step.step || i}><span className="trace-check"><Check size={12}/></span><div><b>{step.name || step.step || `Step ${i+1}`}</b><small>{step.time_ms ?? step.duration_ms ?? 0} ms</small></div></div>)}</div>
            <div className="rag-result-head"><b>Retrieved articles</b><span>{(resolution.articles || []).length} found</span></div>
            {(resolution.articles || []).length ? (resolution.articles || []).map((a,i)=><div className="rag-article" key={a.slug || a.title || i}><div><b>{a.title || a.slug}</b><span className="category-pill">{a.category || 'Knowledge base'}</span></div><strong>{Math.round((a.score ?? a.relevance ?? 0)*100)}%</strong></div>) : <p className="muted">No matching article was retrieved.</p>}
            <div className="rag-result-head"><b>Generated answer</b><span className={`confidence-pill ${Number(resolution.confidence ?? resolution.confidence_score ?? 0)>=.8?'green':Number(resolution.confidence ?? resolution.confidence_score ?? 0)>=.6?'amber':'red'}`}>Confidence {confidence(resolution.confidence ?? resolution.confidence_score)}</span></div>
            {resolution.needs_human_review && <div className="human-review"><AlertCircle size={16}/> Needs human review — an engineer should verify this response.</div>}
            <div className="generated-reply">{resolution.response_text || (resolution.steps || []).map((x,i)=>`${i+1}. ${x}`).join('\n')}</div>
            <div className="rag-sources"><b>Sources</b><span>{(resolution.sources || []).join(', ') || 'No sources available'}</span></div>
            <div className="rag-actions"><button className="outline-button compact" onClick={regenerateResolution} disabled={resolutionLoading}><RefreshCw size={14}/> Regenerate</button><button className="primary-button compact" onClick={copyResolution}><Check size={14}/> Copy reply</button></div>
          </> : <Empty title="No resolution available" detail="Generate a resolution to see retrieved articles and suggested steps."/>}
        </div><div className="drawer-section"><div className="drawer-section-title"><h4>Lifecycle & activity</h4><span>{history.length} events</span></div><div className="lifecycle">{STATUSES.map((s, i) => {const activeIndex = STATUSES.indexOf(selected.status);return <div key={s} className={`lifecycle-step ${i <= activeIndex ? 'done' : ''} ${i === activeIndex ? 'current' : ''}`}><div className="lifecycle-marker">{i < activeIndex ? <Check size={12}/> : i+1}</div><div><b>{s}</b><span>{i === activeIndex ? 'Current status' : i < activeIndex ? 'Completed' : 'Upcoming'}</span></div></div>;})}</div><div className="activity-list">{historyLoading ? <div className="inline-loading"><LoaderCircle className="spin" size={17}/> Loading activity...</div> : history.length ? history.map(log => <div className="activity-item" key={log.log_id}><div className="activity-dot"><Activity size={13}/></div><div><b>{log.action}</b><span>{log.performed_by || 'system'} · {dateText(log.timestamp)}</span></div></div>) : <p className="muted">No activity history found.</p>}</div></div></div><div className="drawer-footer"><div className="status-next"><span>Next status</span><b>{NEXT_STATUS[selected.status] || 'No further actions'}</b></div><button className="primary-button" onClick={changeStatus} disabled={!NEXT_STATUS[selected.status] || statusSaving}>{statusSaving ? <LoaderCircle className="spin" size={16}/> : <ArrowRight size={16}/>} {NEXT_STATUS[selected.status] ? `Move to ${NEXT_STATUS[selected.status]}` : 'Ticket closed'}</button></div></aside></div>}
    <Toast toast={toast} onClose={() => setToast(null)}/>
  </div>;
}
function Metric({ title, value, sub, icon: Icon, tone, trend }) { return <div className="metric-card"><div className="metric-top"><span>{title}</span><div className={`metric-icon ${tone}`}><Icon size={19}/></div></div><div className="metric-value">{value}</div><div className="metric-bottom"><span>{sub}</span><span className="metric-trend">{trend}</span></div></div>; }
function Breakdown({ title, data, colors, large = false }) {
  const entries = Object.entries(data || {}).filter(([,v]) => Number(v) > 0).sort((a,b) => b[1]-a[1]); const total = entries.reduce((sum,[,v]) => sum + Number(v), 0) || 1;
  return <div className={`breakdown ${large ? 'breakdown-large' : ''}`}>{title && <div className="breakdown-title">{title}<span>{entries.reduce((s,[,v])=>s+Number(v),0)} total</span></div>}{entries.length ? <>{large && <div className="stacked-bar">{entries.map(([name,value],i)=><i key={name} title={`${name}: ${value}`} style={{width:`${Number(value)/total*100}%`,background:colors[i%colors.length]}}/>)}</div>}<div className="breakdown-list">{entries.map(([name,value],i)=><div className="breakdown-row" key={name}><span className="breakdown-name"><i style={{background:colors[i%colors.length]}}/>{name}</span><div className="breakdown-track"><i style={{width:`${Number(value)/Math.max(...entries.map(([,v])=>Number(v)))*100}%`,background:colors[i%colors.length]}}/></div><b>{value}</b><span className="breakdown-percent">{Math.round(Number(value)/total*100)}%</span></div>)}</div></> : <div className="breakdown-empty">No ticket data yet</div>}</div>;
}
function TicketTable({ tickets, loading, onOpen }) {
  if (loading && !tickets.length) return <div className="table-loading"><LoaderCircle className="spin" size={22}/><span>Loading tickets from backend...</span></div>;
  if (!tickets.length) return <Empty title="No tickets to show" detail="Create a ticket or change your filters to get started."/>;
  return <div className="table-scroll"><table className="ticket-table"><thead><tr><th>Ticket</th><th>Requester</th><th>Category</th><th>Severity</th><th>Priority</th><th>Status</th><th>Created</th><th/></tr></thead><tbody>{tickets.map(t=><tr key={t.ticket_id} onClick={()=>onOpen(t)}><td><div className="ticket-cell"><div className="ticket-symbol"><Ticket size={16}/></div><div><b>{t.ticket_code || `#${t.ticket_id}`}</b><span>{t.subject || (t.description || '').slice(0,48) || 'Support request'}</span></div></div></td><td><div className="requester-cell"><div className="mini-avatar">{(t.requester_email || '?').slice(0,1).toUpperCase()}</div><span>{t.requester_email || 'Unknown'}</span></div></td><td><span className="category-pill">{t.category || 'Unclassified'}</span></td><td><span className="severity-label"><i className={`severity-dot ${severityClass(t.severity)}`}/>{t.severity || '—'}</span></td><td><span className={`priority-badge ${t.priority === 'P1' ? 'p1' : t.priority === 'P2' ? 'p2' : ''}`}>{t.priority || '—'}</span></td><td><span className={`status-badge ${statusClass(t.status)}`}><i/>{t.status}</span></td><td className="date-cell">{shortDate(t.created_at)}</td><td><button className="row-open" aria-label="Open ticket"><ChevronRight size={17}/></button></td></tr>)}</tbody></table></div>;
}
export default App;
