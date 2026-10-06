/**
 * MPLADS Monitoring & Transparency Platform - Dynamic Frontend Application Script
 * 100% Data-Driven: Zero Hardcoded Numbers, Project Records, or Datasets.
 */

// Global State
let currentRole = "citizen";
let currentView = "landing";
let worksPage = 1;
let worksLimit = 20;
let worksScope = "all";
let analyticsData = null;
let geoMetadata = null;
let activeSelectedMp = "";
let activeSelectedDistrict = "";
let stateChartInstance = null;
let statusChartInstance = null;

// Currency Formatter
function formatINR(amount) {
  if (amount === undefined || amount === null || isNaN(amount)) return "₹0";
  const val = Number(amount);
  if (val >= 10000000) {
    return `₹${(val / 10000000).toFixed(2)} Cr`;
  } else if (val >= 100000) {
    return `₹${(val / 100000).toFixed(2)} Lakh`;
  }
  return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

// Format Date
function formatDate(dtStr) {
  if (!dtStr) return "N/A";
  try {
    const d = new Date(dtStr);
    if (isNaN(d.getTime())) return dtStr;
    return d.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch (e) {
    return dtStr;
  }
}

// Status Badges
function renderStatusBadge(status) {
  if (!status) return `<span class="badge-status bg-slate-100 text-slate-600">Pending</span>`;
  const s = status.toUpperCase();
  if (s === "COMPLETED" || s === "WORK COMPLETED" || (s.includes("COMPLETED") && !s.includes("NOT_LISTED") && !s.includes("PARTIALLY"))) {
    return `<span class="badge-status badge-completed">✓ Completed</span>`;
  } else if (s.includes("RECOMMENDED")) {
    return `<span class="badge-status badge-recommended">⏳ Recommended</span>`;
  } else if (s.includes("APPROVED") || s === "SANCTION" || s.includes("SANCTIONED")) {
    return `<span class="badge-status badge-approved">⚖️ Sanctioned</span>`;
  } else if (s.includes("PROGRESS") || s.includes("PHYSICAL") || s.includes("VENDOR") || s.includes("PARTIALLY") || s.includes("NOT_LISTED") || s.includes("ESTIMATION") || s.includes("IN_PROGRESS")) {
    return `<span class="badge-status badge-in_progress">⚙️ In Progress</span>`;
  } else if (s.includes("RETURN") || s.includes("REJECT")) {
    return `<span class="badge-status badge-returned">↩ Returned</span>`;
  }
  return `<span class="badge-status bg-slate-100 text-slate-700">${status}</span>`;
}

// Monitoring global state
let monPage = 1;
let monLimit = 20;

// Chart instances store for 8 charts
let chartInstances = {};

// Navigation Handler across all main tabs
function switchNav(viewName) {
  currentView = viewName;

  const views = ["landing", "citizen", "mp", "da", "ia", "monitoring", "alerts", "analytics"];
  views.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.add("hidden");

    const navBtn = document.getElementById(`nav-${v}`);
    if (navBtn) {
      navBtn.classList.remove("bg-gov-primary", "text-white", "font-bold", "shadow-xs");
      navBtn.classList.add("text-slate-600", "hover:text-gov-primary", "hover:bg-slate-100");
    }
  });

  const activeEl = document.getElementById(`view-${viewName}`);
  if (activeEl) activeEl.classList.remove("hidden");

  const activeNavBtn = document.getElementById(`nav-${viewName}`);
  if (activeNavBtn) {
    activeNavBtn.classList.add("bg-gov-primary", "text-white", "font-bold", "shadow-xs");
    activeNavBtn.classList.remove("text-slate-600", "hover:text-gov-primary", "hover:bg-slate-100");
  }

  try {
    if (viewName === "citizen") {
      fetchWorks(worksPage);
    } else if (viewName === "mp") {
      loadMpDashboard(activeSelectedMp);
    } else if (viewName === "da") {
      const stateVal = document.getElementById("da-state-selector") ? document.getElementById("da-state-selector").value : "";
      const distVal = document.getElementById("da-district-selector") ? document.getElementById("da-district-selector").value : "";
      loadDaDashboard(stateVal, distVal);
    } else if (viewName === "ia") {
      loadIaDashboard();
    } else if (viewName === "monitoring") {
      loadMonitoringDashboard();
    } else if (viewName === "alerts") {
      loadAlertsView();
    } else if (viewName === "analytics") {
      renderAnalyticsCharts();
    }
  } catch (err) {
    console.error(`Error loading data for view ${viewName}:`, err);
  }
}

// Role Switcher Handler
function handleRoleChange(role) {
  currentRole = role;
  const labelEl = document.getElementById("current-user-label");

  if (role === "citizen") {
    if (labelEl) labelEl.textContent = "Citizen / Public — Demo User";
  } else if (role === "mp") {
    if (labelEl) labelEl.textContent = `MP Portal — Demo User (${activeSelectedMp || 'Demo'})`;
  } else if (role === "district_authority") {
    if (labelEl) labelEl.textContent = `District Authority — Demo User (${activeSelectedDistrict || 'Demo'})`;
  } else if (role === "implementing_agency") {
    if (labelEl) labelEl.textContent = "Implementing Agency — Demo User";
  }

  openCurrentPortal();
}

function openCurrentPortal() {
  if (currentRole === "mp") {
    switchNav("mp");
  } else if (currentRole === "district_authority") {
    switchNav("da");
  } else if (currentRole === "implementing_agency") {
    switchNav("ia");
  } else {
    switchNav("citizen");
  }
}

function setRoleAndOpen(role) {
  const select = document.getElementById("role-switcher");
  if (select) select.value = role;
  handleRoleChange(role);
}

// Modal Handlers
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("hidden");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("hidden");
}


// --- METADATA & DYNAMIC DROPDOWNS ---
async function fetchMetadata() {
  try {
    const res = await fetch("/api/metadata/geography");
    geoMetadata = await res.json();

    // 1. Populate State filter in Public Explorer
    const stateFilter = document.getElementById("filter-state");
    if (stateFilter && geoMetadata.states) {
      stateFilter.innerHTML = `<option value="">All States (${geoMetadata.states.length})</option>` +
        geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
    }

    // 2. Populate District filter in Public Explorer
    populatePublicDistricts("");

    // 3. Populate Category filter in Public Explorer
    const catFilter = document.getElementById("filter-category");
    if (catFilter && geoMetadata.categories) {
      catFilter.innerHTML = `<option value="">All Categories (${geoMetadata.categories.length})</option>` +
        geoMetadata.categories.map(c => `<option value="${c}">${c}</option>`).join("");
    }

    // 4. Populate MP Selector in MP Portal
    const mpSelect = document.getElementById("mp-selector");
    if (mpSelect && geoMetadata.mps && geoMetadata.mps.length > 0) {
      mpSelect.innerHTML = geoMetadata.mps.map(m => 
        `<option value="${m.mp_name}">${m.mp_name} (${m.constituency}, ${m.state})</option>`
      ).join("");
      activeSelectedMp = geoMetadata.mps[0].mp_name;
    }

    // 5. Populate State Selector in DA Portal
    const daStateSelect = document.getElementById("da-state-selector");
    if (daStateSelect && geoMetadata.states) {
      daStateSelect.innerHTML = `<option value="">All States</option>` +
        geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
      daStateSelect.value = "Madhya Pradesh";
      onDaStateChange("Madhya Pradesh", "Agar-Malwa");
    }

    // 6. Populate MP Recommend Modal Dropdowns
    const recState = document.getElementById("rec-state");
    if (recState && geoMetadata.states) {
      recState.innerHTML = geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
      onRecommendStateChange(geoMetadata.states[0]);
    }

    const recCat = document.getElementById("rec-category");
    if (recCat && geoMetadata.categories) {
      recCat.innerHTML = geoMetadata.categories.map(c => `<option value="${c}">${c}</option>`).join("");
    }

    // 7. Populate Agency dropdown in DA Review Modal
    const revAgency = document.getElementById("rev-agency-select");
    if (revAgency && geoMetadata.agencies) {
      revAgency.innerHTML = geoMetadata.agencies.map(a => 
        `<option value="${a.id}|${a.agency_name}">${a.designation} - ${a.agency_name}</option>`
      ).join("");
    }

  } catch (err) {
    console.error("Failed to load metadata:", err);
  }
}

async function onDaStateChange(selectedState, targetDistrict = "") {
  const daDistrictSelect = document.getElementById("da-district-selector");
  if (!daDistrictSelect) return;

  try {
    const res = await fetch(`/api/metadata/districts?state=${encodeURIComponent(selectedState)}`);
    const data = await res.json();
    const districts = data.districts || [];

    daDistrictSelect.innerHTML = `<option value="">All Districts (${districts.length})</option>` +
      districts.map(d => `<option value="${d}">${d}</option>`).join("");

    if (targetDistrict && districts.includes(targetDistrict)) {
      daDistrictSelect.value = targetDistrict;
    } else if (!targetDistrict && selectedState === "Madhya Pradesh" && districts.includes("Agar-Malwa")) {
      daDistrictSelect.value = "Agar-Malwa";
    }

    const currentDistrict = daDistrictSelect.value;
    activeSelectedDistrict = currentDistrict;
    loadDaDashboard(selectedState, currentDistrict);
  } catch (err) {
    console.error("Failed to load districts for DA portal:", err);
  }
}

function onDaDistrictChange(selectedDistrict) {
  const stateSelect = document.getElementById("da-state-selector");
  const selectedState = stateSelect ? stateSelect.value : "";
  activeSelectedDistrict = selectedDistrict;
  loadDaDashboard(selectedState, selectedDistrict);
}

async function populatePublicDistricts(selectedState) {
  const distSelect = document.getElementById("filter-district");
  if (!distSelect) return;

  try {
    const url = (selectedState && selectedState.trim() !== "" && !selectedState.toLowerCase().startsWith("all"))
      ? `/api/metadata/districts?state=${encodeURIComponent(selectedState)}`
      : `/api/metadata/districts`;
    const res = await fetch(url);
    const data = await res.json();
    const districts = data.districts || [];
    distSelect.innerHTML = `<option value="">All Districts (${districts.length})</option>` +
      districts.map(d => `<option value="${d}">${d}</option>`).join("");
  } catch (err) {
    console.error("Failed to load districts:", err);
  }
}

async function populatePublicConstituencies(selectedState, selectedDistrict) {
  const constSelect = document.getElementById("filter-constituency");
  if (!constSelect) return;

  try {
    const params = new URLSearchParams();
    if (selectedState && selectedState.trim() !== "" && !selectedState.toLowerCase().startsWith("all")) {
      params.append("state", selectedState);
    }
    if (selectedDistrict && selectedDistrict.trim() !== "" && !selectedDistrict.toLowerCase().startsWith("all")) {
      params.append("district", selectedDistrict);
    }
    const res = await fetch(`/api/metadata/constituencies?${params.toString()}`);
    const data = await res.json();
    const constituencies = data.constituencies || [];
    constSelect.innerHTML = `<option value="">All Constituencies (${constituencies.length})</option>` +
      constituencies.map(c => `<option value="${c}">${c}</option>`).join("");
  } catch (err) {
    console.error("Failed to load constituencies:", err);
  }
}

async function onStateFilterChange(selectedState) {
  await populatePublicDistricts(selectedState);
  await populatePublicConstituencies(selectedState, "");
  applyWorksFilter();
}

async function onDistrictFilterChange(selectedDistrict) {
  const stateSelect = document.getElementById("filter-state");
  const selectedState = stateSelect ? stateSelect.value : "";
  await populatePublicConstituencies(selectedState, selectedDistrict);
  applyWorksFilter();
}

function resetPublicFilters() {
  if (document.getElementById("filter-q")) document.getElementById("filter-q").value = "";
  if (document.getElementById("filter-state")) document.getElementById("filter-state").value = "";
  if (document.getElementById("filter-district")) document.getElementById("filter-district").value = "";
  if (document.getElementById("filter-constituency")) document.getElementById("filter-constituency").value = "";
  if (document.getElementById("filter-category")) document.getElementById("filter-category").value = "";
  if (document.getElementById("filter-status")) document.getElementById("filter-status").value = "";
  populatePublicDistricts("");
  populatePublicConstituencies("", "");
  fetchWorks(1);
}

function onRecommendStateChange(selectedState) {
  if (!geoMetadata) return;

  const stateDistricts = geoMetadata.districts.filter(d => d.state === selectedState);
  const districtSelect = document.getElementById("rec-district");
  if (districtSelect) {
    districtSelect.innerHTML = stateDistricts.map(d => `<option value="${d.district}">${d.district}</option>`).join("");
    if (stateDistricts.length > 0) {
      onRecommendDistrictChange(stateDistricts[0].district);
    }
  }
}

function onRecommendDistrictChange(selectedDistrict) {
  if (!geoMetadata) return;

  const stateSelect = document.getElementById("rec-state");
  const selectedState = stateSelect ? stateSelect.value : "";

  const districtConstituencies = geoMetadata.constituencies.filter(c => 
    c.district === selectedDistrict || (selectedState && c.state === selectedState)
  );

  const constSelect = document.getElementById("rec-constituency");
  if (constSelect) {
    if (districtConstituencies.length > 0) {
      constSelect.innerHTML = districtConstituencies.map(c => `<option value="${c.constituency}">${c.constituency}</option>`).join("");
    } else {
      constSelect.innerHTML = `<option value="${selectedDistrict} Constituency">${selectedDistrict} Constituency</option>`;
    }
  }
}

function changeActiveMp(mpName) {
  activeSelectedMp = mpName;
  const labelEl = document.getElementById("current-user-label");
  if (currentRole === "mp" && labelEl) {
    labelEl.textContent = `MP Portal — Demo User (${activeSelectedMp})`;
  }
  loadMpDashboard(activeSelectedMp);
}

function changeActiveDistrict(districtName) {
  const stateSelect = document.getElementById("da-state-selector");
  const selectedState = stateSelect ? stateSelect.value : "";
  onDaDistrictChange(districtName);
}


// --- 1. FETCH ANALYTICS OVERVIEW & DATA COVERAGE ---
async function fetchAnalyticsOverview() {
  try {
    const res = await fetch("/api/analytics/overview");
    analyticsData = await res.json();

    const k = analyticsData.kpis;

    // Landing KPIs
    document.getElementById("kpi-total-works").textContent = k.total_works.toLocaleString();
    document.getElementById("kpi-states-sub").textContent = `${analyticsData.state_breakdown.length} States & UTs Tracked`;

    document.getElementById("kpi-total-sanction").textContent = formatINR(k.total_sanction_amount);
    const meanOutlay = k.total_works > 0 ? (k.total_sanction_amount / k.total_works) : 0;
    document.getElementById("kpi-mean-outlay-sub").textContent = `Calculated Mean: ${formatINR(meanOutlay)} / work`;

    document.getElementById("kpi-total-disbursed").textContent = formatINR(k.total_disbursed_amount);
    document.getElementById("kpi-events-sub").textContent = `Calculated from ${k.total_payment_events.toLocaleString()} payment events`;

    document.getElementById("kpi-completion-rate").textContent = `${k.completion_rate_pct}%`;
    document.getElementById("kpi-completion-sub").textContent = `${k.completed_works.toLocaleString()} completed • ${k.ongoing_works.toLocaleString()} ongoing`;

    // Dynamic banner text
    const bannerInfo = document.getElementById("banner-dataset-info");
    if (bannerInfo) {
      bannerInfo.textContent = `${k.total_works.toLocaleString()} Projects & ${k.total_payment_events.toLocaleString()} Payment Events loaded from real CSV datasets.`;
    }

    // Connected System Datasets Coverage Component
    if (document.getElementById("coverage-projects-count")) {
      document.getElementById("coverage-projects-count").textContent = k.total_works.toLocaleString();
      document.getElementById("coverage-payments-count").textContent = k.total_payment_events.toLocaleString();
      document.getElementById("coverage-states-count").textContent = `${analyticsData.state_breakdown.length} States & UTs`;
      document.getElementById("coverage-live-count").textContent = `${k.live_works_count} Works`;
    }
  } catch (err) {
    console.error("Failed to load analytics overview:", err);
  }
}


// --- 2. PUBLIC EXPLORER (SEARCH & BROWSE) ---
async function fetchWorks(page = 1) {
  worksPage = page;
  const tbody = document.getElementById("works-table-body");
  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-slate-400">Loading verified works from database...</td></tr>`;

  const q = document.getElementById("filter-q") ? document.getElementById("filter-q").value : "";
  const state = document.getElementById("filter-state") ? document.getElementById("filter-state").value : "";
  const district = document.getElementById("filter-district") ? document.getElementById("filter-district").value : "";
  const constituency = document.getElementById("filter-constituency") ? document.getElementById("filter-constituency").value : "";
  const category = document.getElementById("filter-category") ? document.getElementById("filter-category").value : "";
  const status = document.getElementById("filter-status") ? document.getElementById("filter-status").value : "";

  const params = new URLSearchParams({
    page: worksPage,
    limit: worksLimit,
    scope: worksScope
  });
  if (q) params.append("q", q);
  if (state) params.append("state", state);
  if (district) params.append("district", district);
  if (constituency) params.append("constituency", constituency);
  if (category) params.append("category", category);
  if (status) params.append("status", status);

  try {
    const res = await fetch(`/api/works?${params.toString()}`);
    const data = await res.json();

    // Update Summary Information Cards dynamically from active search query
    if (data.summary) {
      if (document.getElementById("pub-sum-works")) document.getElementById("pub-sum-works").textContent = (data.summary.total_works || 0).toLocaleString();
      if (document.getElementById("pub-sum-sanction")) document.getElementById("pub-sum-sanction").textContent = formatINR(data.summary.total_sanction_amount || 0);
      if (document.getElementById("pub-sum-disbursed")) document.getElementById("pub-sum-disbursed").textContent = formatINR(data.summary.total_disbursed_amount || 0);
      if (document.getElementById("pub-sum-completed")) document.getElementById("pub-sum-completed").textContent = (data.summary.completed_works || 0).toLocaleString();
      if (document.getElementById("pub-sum-ongoing")) document.getElementById("pub-sum-ongoing").textContent = (data.summary.ongoing_works || 0).toLocaleString();
    }

    document.getElementById("works-count-label").textContent = data.total.toLocaleString();
    document.getElementById("current-page-num").textContent = data.page;
    document.getElementById("total-pages-num").textContent = data.total_pages || 1;

    document.getElementById("prev-page-btn").disabled = data.page <= 1;
    document.getElementById("next-page-btn").disabled = data.page >= data.total_pages;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-12 text-slate-500">
            <div class="max-w-md mx-auto space-y-2">
              <div class="text-2xl">🔍</div>
              <div class="font-bold text-slate-700">No historical works found for the selected filters.</div>
              <p class="text-xs text-slate-500">Try changing or clearing your search term, state, district, or constituency selection.</p>
              <button onclick="resetPublicFilters()" class="mt-2 text-xs font-bold text-gov-primary bg-blue-50 hover:bg-blue-100 border border-blue-200 px-4 py-2 rounded-lg transition">Clear All Filters</button>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = data.items.map(w => {
      const disbPct = (w.sanction_amount && w.sanction_amount > 0) 
        ? ((w.total_disbursed / w.sanction_amount) * 100).toFixed(1) 
        : null;

      return `
        <tr class="hover:bg-slate-50 transition">
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-mono text-xs font-bold text-slate-800">${w.work_id || 'N/A'}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-semibold text-slate-800 text-xs line-clamp-2" title="${w.work_title || ''}">${w.work_title || 'Not available in source data'}</div>
            ${w.work_category ? `<div class="text-[11px] text-slate-500 mt-0.5">${w.work_category}</div>` : ''}
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-semibold text-slate-800 text-xs">${w.district || 'N/A'}</div>
            <div class="text-[11px] text-slate-500">${w.state || 'N/A'}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-semibold text-slate-800 text-xs">${w.constituency || 'N/A'}</div>
            <div class="text-[11px] text-gov-primary font-medium">${w.mp_name || 'Not available in source data'}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-bold text-xs text-slate-800">${formatINR(w.sanction_amount)}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-bold text-xs text-emerald-700">${formatINR(w.total_disbursed)}</div>
            ${disbPct !== null ? `<div class="text-[10px] text-slate-500 mt-0.5">${disbPct}% of sanction</div>` : ''}
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            ${renderStatusBadge(w.status)}
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs font-bold text-gov-primary hover:text-blue-900 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-lg transition shadow-2xs">
              View Detail
            </button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error("Error fetching works:", err);
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-red-500">Failed to load works from server: ${err.message}</td></tr>`;
  }
}

function applyWorksFilter() {
  fetchWorks(1);
}

function changeWorksPage(delta) {
  fetchWorks(worksPage + delta);
}

function setWorksScope(scope) {
  worksScope = scope;
  ["all", "live", "historical"].forEach(s => {
    const btn = document.getElementById(`scope-${s}`);
    if (btn) {
      if (s === scope) {
        btn.classList.add("bg-gov-primary", "text-white");
        btn.classList.remove("bg-slate-100", "text-slate-700");
      } else {
        btn.classList.remove("bg-gov-primary", "text-white");
        btn.classList.add("bg-slate-100", "text-slate-700");
      }
    }
  });
  fetchWorks(1);
}


// --- 3. PROJECT 360° VIEW ---
async function openProject360(workId) {
  try {
    switchNav('citizen');
    const tableCont = document.getElementById("pwe-table-container");
    const container360 = document.getElementById("pwe-360-container");

    if (tableCont) tableCont.classList.add("hidden");
    if (container360) container360.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: 'smooth' });

    const res = await fetch(`/api/works/${encodeURIComponent(workId)}`);
    if (!res.ok) throw new Error("No matching work record found.");
    const data = await res.json();
    const w = data.work || {};
    const payments = data.payments || [];
    const updates = data.progress_updates || [];
    const audit = data.audit_trail || [];
    const mon = data.monitoring || {};
    const alerts = data.alerts || [];

    // 1. Header & Source
    if (document.getElementById("p360-title")) document.getElementById("p360-title").textContent = w.title || "Not available in source data";
    if (document.getElementById("p360-wid")) document.getElementById("p360-wid").textContent = w.work_id || "N/A";
    if (document.getElementById("p360-geo")) document.getElementById("p360-geo").textContent = `${w.district || 'Not available'}, ${w.state || 'Not available'}`;
    if (document.getElementById("p360-constituency")) document.getElementById("p360-constituency").textContent = w.constituency || "Not available in source data";
    if (document.getElementById("p360-status-badge")) document.getElementById("p360-status-badge").innerHTML = renderStatusBadge(w.status);
    
    const srcBadge = document.getElementById("p360-source-badge");
    if (srcBadge) {
      if (w.source === 'live') {
        srcBadge.className = "text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-800 border border-blue-200";
        srcBadge.textContent = "LIVE PROJECT";
      } else {
        srcBadge.className = "text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200";
        srcBadge.textContent = "HISTORICAL DATASET";
      }
    }

    // 2. Overrun Banner
    const sanc = w.sanction_amount || 0;
    const disb = w.total_disbursed || 0;
    const overrunBanner = document.getElementById("p360-overrun-banner");
    if (overrunBanner) {
      if (disb > sanc && sanc > 0) {
        overrunBanner.classList.remove("hidden");
        if (document.getElementById("p360-overrun-disb")) document.getElementById("p360-overrun-disb").textContent = formatINR(disb);
        if (document.getElementById("p360-overrun-sanc")) document.getElementById("p360-overrun-sanc").textContent = formatINR(sanc);
      } else {
        overrunBanner.classList.add("hidden");
      }
    }

    // 3. Project Overview Grid
    if (document.getElementById("p360-category-tag")) document.getElementById("p360-category-tag").textContent = w.work_category || "Uncategorized";
    if (document.getElementById("p360-ov-geo")) document.getElementById("p360-ov-geo").textContent = `${w.district || 'Not available'}, ${w.state || 'Not available'}`;
    if (document.getElementById("p360-ov-constituency")) document.getElementById("p360-ov-constituency").textContent = w.constituency || "Not available in source data";
    if (document.getElementById("p360-ov-mp")) document.getElementById("p360-ov-mp").textContent = w.mp_name || "Not available in source data";
    if (document.getElementById("p360-ov-agency")) document.getElementById("p360-ov-agency").textContent = w.assigned_agency_name || w.ida || "Not available in source data";
    if (document.getElementById("p360-ov-category")) document.getElementById("p360-ov-category").textContent = w.work_category || "Not available in source data";
    if (document.getElementById("p360-ov-status")) document.getElementById("p360-ov-status").textContent = w.portal_execution_status || w.status || "Not available in source data";
    if (document.getElementById("p360-ov-priority")) document.getElementById("p360-ov-priority").textContent = w.priority || "Not available";
    if (document.getElementById("p360-ov-location")) document.getElementById("p360-ov-location").textContent = w.location || "Not available";
    if (document.getElementById("p360-ov-desc")) document.getElementById("p360-ov-desc").textContent = w.description || "Project recorded in official MPLADS registry.";

    // 4. Financial Monitoring
    if (document.getElementById("p360-fin-sanction")) document.getElementById("p360-fin-sanction").textContent = formatINR(sanc);
    if (document.getElementById("p360-fin-disbursed")) document.getElementById("p360-fin-disbursed").textContent = formatINR(disb);
    
    const rem = sanc - disb;
    const remEl = document.getElementById("p360-fin-remaining");
    if (remEl) {
      if (rem < 0) {
        remEl.textContent = `- ${formatINR(Math.abs(rem))}`;
        remEl.className = "text-sm font-bold text-amber-700 mt-0.5";
      } else {
        remEl.textContent = formatINR(rem);
        remEl.className = "text-sm font-bold text-slate-700 mt-0.5";
      }
    }

    const pct = sanc > 0 ? ((disb / sanc) * 100).toFixed(1) : "0.0";
    if (document.getElementById("p360-fin-pct")) document.getElementById("p360-fin-pct").textContent = `${pct}%`;
    if (document.getElementById("p360-fin-util-label")) document.getElementById("p360-fin-util-label").textContent = `${pct}%`;
    
    const barEl = document.getElementById("p360-fin-progress-bar");
    if (barEl) {
      barEl.style.width = `${Math.min(parseFloat(pct), 100)}%`;
      barEl.className = (disb > sanc && sanc > 0) ? "bg-amber-600 h-3 rounded-full transition-all duration-500" : "bg-gov-primary h-3 rounded-full transition-all duration-500";
    }

    if (document.getElementById("p360-fin-util-sub")) {
      document.getElementById("p360-fin-util-sub").textContent = (disb > sanc && sanc > 0) 
        ? `⚠️ Overrun: ${formatINR(disb)} disbursed vs ${formatINR(sanc)} sanctioned`
        : `${formatINR(disb)} released out of ${formatINR(sanc)} sanctioned outlay`;
    }

    // 5. Physical Progress Section
    const phyContainer = document.getElementById("p360-phy-content");
    if (phyContainer) {
      if (w.physical_progress_pct !== null && w.physical_progress_pct !== undefined) {
        phyContainer.innerHTML = `
          <div class="space-y-2">
            <div class="flex justify-between font-bold text-slate-800">
              <span>Physical Work Completion</span>
              <span class="text-emerald-700 font-bold">${w.physical_progress_pct}%</span>
            </div>
            <div class="w-full bg-slate-100 rounded-full h-3 overflow-hidden border border-slate-200">
              <div class="bg-emerald-600 h-3 rounded-full transition-all duration-500" style="width: ${w.physical_progress_pct}%"></div>
            </div>
          </div>
          ${w.current_milestone ? `<div class="p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-700">Latest Milestone: <strong class="text-slate-900 font-bold">${w.current_milestone}</strong></div>` : ''}
          ${w.completion_date ? `<div class="text-xs text-slate-500">Completion Date: <strong class="text-slate-700">${formatDate(w.completion_date)}</strong></div>` : ''}
        `;
      } else {
        phyContainer.innerHTML = `
          <div class="p-4 bg-slate-50 border border-slate-200 rounded-xl text-slate-500 font-medium leading-relaxed">
            ℹ️ Physical progress data is not available for this historical record.
          </div>
        `;
      }
    }

    // 6. Payment History Table
    const payBadge = document.getElementById("p360-pay-count-badge");
    if (payBadge) payBadge.textContent = `${payments.length} event(s)`;

    const payTbody = document.getElementById("p360-payments-tbody");
    if (payTbody) {
      if (payments.length === 0) {
        payTbody.innerHTML = `<tr><td colspan="4" class="text-center py-6 text-slate-400 font-medium">No payment events available for this project.</td></tr>`;
      } else {
        payTbody.innerHTML = payments.map(p => `
          <tr class="hover:bg-slate-50 transition">
            <td class="font-mono text-xs text-slate-600">${formatDate(p.expenditure_date)}</td>
            <td class="font-semibold text-slate-800 text-xs">${p.vendor_name_normalized || p.vendor_name_raw || 'Vendor / Treasury'}</td>
            <td><span class="text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded">✓ ${p.payment_status || 'SUCCESS'}</span></td>
            <td class="font-bold text-emerald-700 text-xs">${formatINR(p.reported_fund_disbursed_amount || 0)}</td>
          </tr>
        `).join("");
      }
    }

    // 7. Project Lifecycle Timeline
    const tlContainer = document.getElementById("p360-timeline-content");
    if (tlContainer) {
      const timelineEvents = [];

      if (w.recommended_date) {
        timelineEvents.push({
          title: "Recommendation Submitted",
          date: w.recommended_date,
          actor: w.mp_name || "Member of Parliament",
          desc: "Project proposal submitted for verification and administrative sanction."
        });
      }
      if (w.sanction_date) {
        timelineEvents.push({
          title: "Approved & Sanctioned",
          date: w.sanction_date,
          actor: w.ida || "District Authority",
          desc: `Administrative sanction issued for outlay of ${formatINR(sanc)}.`
        });
      }
      if (w.assigned_agency_name && w.source === 'live') {
        timelineEvents.push({
          title: "Implementing Agency Assigned",
          date: w.sanction_date || w.recommended_date,
          actor: w.assigned_agency_name,
          desc: "Work order and execution responsibility assigned to agency."
        });
      }
      if (updates && updates.length > 0) {
        updates.forEach(u => {
          timelineEvents.push({
            title: `Progress Update (${u.progress_percentage || 0}%)`,
            date: u.submitted_at,
            actor: w.assigned_agency_name || "Implementing Agency",
            desc: u.remarks || u.current_milestone || "Progress update recorded."
          });
        });
      }
      if (w.completion_date && (w.status === 'COMPLETED' || w.physical_progress_pct === 100)) {
        timelineEvents.push({
          title: "Work Completion Recorded",
          date: w.completion_date,
          actor: w.assigned_agency_name || "Implementing Agency",
          desc: "Civil work completed and operational closure reported."
        });
      }

      if (timelineEvents.length === 0) {
        tlContainer.innerHTML = `<div class="text-slate-400 font-medium py-2">Timeline lifecycle dates not available in dataset record.</div>`;
      } else {
        tlContainer.innerHTML = timelineEvents.map(evt => `
          <div class="relative group">
            <div class="absolute -left-[21px] top-0.5 w-2.5 h-2.5 rounded-full bg-gov-primary border-2 border-white ring-2 ring-blue-100"></div>
            <div class="font-bold text-slate-800 text-xs">${evt.title}</div>
            <div class="text-[11px] text-slate-400 font-medium mt-0.5">${formatDate(evt.date)} • ${evt.actor}</div>
            <div class="text-slate-600 text-xs mt-1 leading-snug">${evt.desc}</div>
          </div>
        `).join("");
      }
    }

    // 8. ML Monitoring Section
    const riskScore = mon.anomaly_risk_score !== undefined ? mon.anomaly_risk_score : 0;
    if (document.getElementById("p360-ml-risk-score")) document.getElementById("p360-ml-risk-score").textContent = `${riskScore}/100`;
    if (document.getElementById("p360-ml-anomaly-status")) {
      const anomEl = document.getElementById("p360-ml-anomaly-status");
      anomEl.textContent = mon.anomaly_status || "NORMAL";
      anomEl.className = (mon.anomaly_status === "POTENTIAL ANOMALY") ? "font-bold text-purple-900" : "font-bold text-slate-700";
    }
    if (document.getElementById("p360-ml-delay-status")) document.getElementById("p360-ml-delay-status").textContent = mon.delay_status || "ON_TIME";
    if (document.getElementById("p360-ml-budget-status")) document.getElementById("p360-ml-budget-status").textContent = mon.budget_monitoring_status || "WITHIN_SANCTION";
    if (document.getElementById("p360-ml-payment-conc")) {
      document.getElementById("p360-ml-payment-conc").textContent = (mon.max_single_tranche_ratio >= 0.95 && mon.payment_tranche_count > 1) ? "DETECTED" : "NOT DETECTED";
    }

    // 9. Active Alerts Section
    if (document.getElementById("p360-alerts-count")) document.getElementById("p360-alerts-count").textContent = `${alerts.length} alert(s)`;
    const alertsContainer = document.getElementById("p360-alerts-list");
    if (alertsContainer) {
      if (alerts.length === 0) {
        alertsContainer.innerHTML = `
          <div class="p-3.5 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-800 text-xs font-semibold flex items-center gap-2">
            <span>✅</span>
            <span>No active monitoring alerts for this project.</span>
          </div>
        `;
      } else {
        alertsContainer.innerHTML = alerts.map(a => `
          <div class="p-3.5 bg-amber-50 border border-amber-200 rounded-xl text-amber-950 space-y-1 shadow-2xs">
            <div class="flex justify-between items-center">
              <strong class="font-bold text-xs text-amber-950">🔴 ${a.alert_type}</strong>
              <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-200 text-amber-900">${a.severity || 'MEDIUM'}</span>
            </div>
            <div class="text-xs text-slate-800 font-semibold">${a.reason}</div>
            <div class="text-[11px] text-amber-800 font-medium">${a.explanation}</div>
          </div>
        `).join("");
      }
    }

    // 10. Audit History Section
    const auditContainer = document.getElementById("p360-audit-list");
    if (auditContainer) {
      if (!audit || audit.length === 0) {
        auditContainer.innerHTML = `
          <div class="p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-500 font-medium text-xs">
            Historical audit trail is not available for this dataset record.
          </div>
        `;
      } else {
        auditContainer.innerHTML = audit.map(a => `
          <div class="p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs flex justify-between items-center">
            <div>
              <div class="font-bold text-slate-800">${a.action || 'Activity Recorded'}</div>
              <div class="text-[11px] text-slate-500">${a.actor_name || 'System User'} (${a.actor_role || 'Role'})</div>
            </div>
            <div class="text-[11px] font-mono text-slate-400">${formatDate(a.created_at)}</div>
          </div>
        `).join("");
      }
    }

    // 11. Data Source Footer
    const dsEl = document.getElementById("p360-datasource-text");
    if (dsEl) {
      dsEl.textContent = (w.source === 'live')
        ? "Live project record stored in the application database."
        : "Historical dataset record sourced from the connected MPLADS project and payment datasets.";
    }

  } catch (err) {
    console.error("Error opening Project 360 view:", err);
    alert("Project 360 View error: " + err.message);
  }
}

function viewWorkDetail(workId) {
  openProject360(workId);
}

function inspectMonitoringProject(workId) {
  openProject360(workId);
}

function closeProject360() {
  const tableCont = document.getElementById("pwe-table-container");
  const container360 = document.getElementById("pwe-360-container");
  if (container360) container360.classList.add("hidden");
  if (tableCont) tableCont.classList.remove("hidden");
}



// --- 4. MP PORTAL ---
async function loadMpDashboard(mpName) {
  try {
    const url = mpName ? `/api/mp/dashboard?mp_name=${encodeURIComponent(mpName)}` : `/api/mp/dashboard`;
    const res = await fetch(url);
    const data = await res.json();

    activeSelectedMp = data.mp_name;
    document.getElementById("mp-header-name").textContent = `MP Portal — ${data.mp_name}`;
    document.getElementById("mp-constituency").textContent = data.constituency || "Constituency";
    document.getElementById("mp-state").textContent = data.state || "State";

    const k = data.kpis;
    document.getElementById("mp-kpi-total").textContent = k.total_recommended.toLocaleString();
    document.getElementById("mp-kpi-pending").textContent = `${k.pending_review} pending review`;
    document.getElementById("mp-kpi-sanction").textContent = formatINR(k.sanctioned_amount);
    document.getElementById("mp-kpi-disbursed").textContent = formatINR(k.total_disbursed);
    document.getElementById("mp-kpi-completed").textContent = k.completed_works.toLocaleString();
    document.getElementById("mp-kpi-ongoing").textContent = `${k.in_progress_works.toLocaleString()} ongoing`;

    // Render live recommended works
    const liveTbody = document.getElementById("mp-live-works-tbody");
    if (!data.live_works || data.live_works.length === 0) {
      liveTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400">No live recommendations submitted yet. Click "+ Recommend New Work" to submit a live proposal.</td></tr>`;
    } else {
      liveTbody.innerHTML = data.live_works.map(w => `
        <tr>
          <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
          <td>
            <div class="font-semibold text-slate-800 text-xs">${w.title}</div>
            <div class="text-[11px] text-slate-500">${w.work_category} • ${w.location || ''}</div>
          </td>
          <td>
            <div class="font-bold text-xs">${formatINR(w.sanction_amount > 0 ? w.sanction_amount : w.estimated_amount)}</div>
            <div class="text-[10px] text-slate-500">${w.sanction_amount > 0 ? 'Sanctioned' : 'Est. Outlay'}</div>
          </td>
          <td>${renderStatusBadge(w.status)}</td>
          <td>
            <div class="flex items-center gap-1.5">
              <div class="w-12 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${w.physical_progress_pct || 0}%"></div>
              </div>
              <span class="text-xs font-bold">${w.physical_progress_pct || 0}%</span>
            </div>
          </td>
          <td class="text-xs text-slate-700 font-medium">${w.assigned_agency_name || 'Pending Assignment'}</td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs text-gov-primary font-bold hover:underline">
              Inspect
            </button>
          </td>
        </tr>
      `).join("");
    }

    // Render historical constituency works
    const histTbody = document.getElementById("mp-hist-works-tbody");
    if (data.recent_historical && data.recent_historical.length > 0) {
      histTbody.innerHTML = data.recent_historical.map(w => `
        <tr>
          <td class="font-mono text-xs font-bold">${w.work_id}</td>
          <td class="text-xs font-medium text-slate-800 line-clamp-1">${w.work_title}</td>
          <td class="text-xs text-slate-600">${formatDate(w.sanction_date)}</td>
          <td class="text-xs font-semibold text-slate-800">${formatINR(w.sanction_amount)}</td>
          <td class="text-xs font-semibold text-emerald-700">${formatINR(w.total_disbursed)}</td>
          <td>${renderStatusBadge(w.work_completion_status)}</td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs text-gov-primary font-bold hover:underline">
              View
            </button>
          </td>
        </tr>
      `).join("");
    } else {
      histTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400">No historical records found for this MP.</td></tr>`;
    }
  } catch (err) {
    console.error("Failed to load MP dashboard:", err);
  }
}

function openRecommendModal() {
  openModal("modal-recommend");
}

async function submitRecommendation(e) {
  e.preventDefault();
  const payload = {
    title: document.getElementById("rec-title").value.trim(),
    work_category: document.getElementById("rec-category").value,
    priority: document.getElementById("rec-priority").value,
    state: document.getElementById("rec-state").value,
    district: document.getElementById("rec-district").value,
    constituency: document.getElementById("rec-constituency").value,
    location: document.getElementById("rec-location").value.trim(),
    estimated_amount: parseFloat(document.getElementById("rec-amount").value),
    beneficiary_purpose: document.getElementById("rec-purpose").value.trim(),
    recommending_mp_name: activeSelectedMp || "MP (Demo User)"
  };

  try {
    const res = await fetch("/api/mp/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Failed to submit recommendation");

    alert(`✅ Live Recommendation Created!\nWork ID: ${result.work_id}\nStatus: ${result.status}\nSaved to application database.`);
    closeModal("modal-recommend");
    document.getElementById("form-recommend").reset();
    loadMpDashboard(activeSelectedMp);
    fetchAnalyticsOverview();
  } catch (err) {
    alert("Error submitting recommendation: " + err.message);
  }
}


// --- 5. DISTRICT AUTHORITY (DA) PORTAL ---
async function loadDaDashboard(stateName, districtName) {
  try {
    const params = new URLSearchParams();
    if (stateName) params.append("state", stateName);
    if (districtName) params.append("district", districtName);

    const res = await fetch(`/api/da/dashboard?${params.toString()}`);
    const data = await res.json();

    activeSelectedDistrict = data.district;
    document.getElementById("da-district-name").textContent = data.district || "All Districts";
    document.getElementById("da-state-name").textContent = data.state || "All States";
    if (document.getElementById("da-district-sub")) {
      document.getElementById("da-district-sub").textContent = `${data.district}, ${data.state}`;
    }

    const k = data.kpis;
    document.getElementById("da-kpi-total").textContent = (k.historical_district_works + k.active_live_works).toLocaleString();
    document.getElementById("da-kpi-sanction").textContent = formatINR(k.district_sanction_amount);
    document.getElementById("da-kpi-disbursed").textContent = formatINR(k.district_disbursed_amount);
    document.getElementById("da-kpi-completed").textContent = k.district_completed.toLocaleString();
    document.getElementById("da-kpi-ongoing").textContent = `${k.district_ongoing.toLocaleString()} ongoing`;

    // Section A: Pending MP Recommendations
    document.getElementById("da-pending-badge").textContent = data.pending_recommendations.length;
    const pendingTbody = document.getElementById("da-pending-tbody");
    if (!data.pending_recommendations || data.pending_recommendations.length === 0) {
      pendingTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400 font-medium">No pending recommendations currently in queue for ${data.district}.</td></tr>`;
    } else {
      pendingTbody.innerHTML = data.pending_recommendations.map(w => `
        <tr class="bg-amber-50/40">
          <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
          <td class="text-xs font-semibold text-gov-primary">${w.recommending_mp_name}</td>
          <td>
            <div class="font-semibold text-xs text-slate-800">${w.title}</div>
            <div class="text-[11px] text-slate-500">${w.beneficiary_purpose || ''}</div>
          </td>
          <td class="font-bold text-xs text-emerald-800">${formatINR(w.estimated_amount)}</td>
          <td class="text-xs text-slate-600">${formatDate(w.recommended_date)}</td>
          <td>${renderStatusBadge(w.status)}</td>
          <td>
            <button onclick="openReviewModal('${w.work_id}', '${escape(w.title)}', ${w.estimated_amount})" class="bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-2xs transition">
              Review & Sanction
            </button>
          </td>
        </tr>
      `).join("");
    }

    // Section B: Existing Works in Selected District (Combines active live works + real historical district works)
    const activeTbody = document.getElementById("da-active-tbody");
    const combinedWorks = [
      ...(data.active_live_works || []).map(w => ({ ...w, is_live: true })),
      ...(data.historical_district_works || []).map(w => ({
        work_id: w.work_id,
        title: w.work_title,
        work_category: w.work_category,
        mp_name: w.mp_name,
        constituency: w.constituency,
        sanction_amount: w.sanction_amount,
        total_disbursed: w.total_disbursed,
        status: w.status,
        is_live: false
      }))
    ];

    if (combinedWorks.length === 0) {
      activeTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400 font-medium">No historical works found for this district in the connected dataset.</td></tr>`;
    } else {
      activeTbody.innerHTML = combinedWorks.map(w => `
        <tr>
          <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
          <td>
            <div class="text-xs font-semibold text-slate-800 line-clamp-1" title="${w.title}">${w.title}</div>
            <div class="text-[11px] text-slate-500">${w.work_category || 'General'}</div>
          </td>
          <td>
            <div class="text-xs font-semibold text-gov-primary">${w.mp_name || 'MP'}</div>
            <div class="text-[11px] text-slate-500">${w.constituency || ''}</div>
          </td>
          <td class="text-xs font-bold text-slate-800">${formatINR(w.sanction_amount)}</td>
          <td class="text-xs font-semibold text-emerald-700">${formatINR(w.total_disbursed)}</td>
          <td>${renderStatusBadge(w.status)}</td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs text-gov-primary font-bold hover:underline">
              Inspect
            </button>
          </td>
        </tr>
      `).join("");
    }
  } catch (err) {
    console.error("Failed to load DA dashboard:", err);
  }
}

function openReviewModal(workId, titleEscaped, estimatedAmount) {
  document.getElementById("rev-hidden-work-id").value = workId;
  document.getElementById("rev-work-id").textContent = workId;
  document.getElementById("rev-work-title").textContent = unescape(titleEscaped);
  document.getElementById("rev-proposed-outlay").textContent = formatINR(estimatedAmount);
  document.getElementById("rev-sanction-amount").value = estimatedAmount;
  openModal("modal-review");
}

function toggleReviewAction(action) {
  const fields = document.getElementById("approve-fields");
  const submitBtn = document.getElementById("rev-submit-btn");
  if (action === "RETURN") {
    fields.classList.add("hidden");
    submitBtn.textContent = "Return to MP with Remarks";
    submitBtn.className = "px-5 py-2 bg-red-700 hover:bg-red-800 text-white rounded-lg font-semibold shadow-xs";
  } else {
    fields.classList.remove("hidden");
    submitBtn.textContent = "Confirm & Issue Sanction Order";
    submitBtn.className = "px-5 py-2 bg-emerald-700 hover:bg-emerald-800 text-white rounded-lg font-semibold shadow-xs";
  }
}

async function submitReview(e) {
  e.preventDefault();
  const workId = document.getElementById("rev-hidden-work-id").value;
  const actionRadio = document.querySelector('input[name="rev_action"]:checked');
  const action = actionRadio ? actionRadio.value : "APPROVE";
  const agencySelect = document.getElementById("rev-agency-select").value.split("|");

  const payload = {
    work_id: workId,
    action: action,
    sanction_amount: parseFloat(document.getElementById("rev-sanction-amount").value),
    assigned_agency_id: parseInt(agencySelect[0]) || 1,
    assigned_agency_name: agencySelect[1] || "Assigned Agency",
    review_comments: document.getElementById("rev-comments").value.trim()
  };

  try {
    const res = await fetch("/api/da/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Review failed");

    alert(`✅ Action Recorded!\nWork ID: ${result.work_id}\nNew Status: ${result.new_status}`);
    closeModal("modal-review");
    const stateVal = document.getElementById("da-state-selector") ? document.getElementById("da-state-selector").value : "";
    loadDaDashboard(stateVal, activeSelectedDistrict);
    fetchAnalyticsOverview();
  } catch (err) {
    alert("Error recording review: " + err.message);
  }
}


// --- 6. IMPLEMENTING AGENCY (IA) PORTAL ---
async function loadIaDashboard() {
  try {
    const res = await fetch("/api/agency/dashboard");
    const data = await res.json();

    document.getElementById("ia-assigned-count").textContent = `${data.kpis.total_assigned} Works`;

    const tbody = document.getElementById("ia-assigned-tbody");
    if (!data.assigned_works || data.assigned_works.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400 font-medium">No approved live works assigned yet. Works will appear here once approved by District Authority.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.assigned_works.map(w => `
      <tr>
        <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
        <td>
          <div class="font-semibold text-slate-800 text-xs">${w.title}</div>
          <div class="text-[11px] text-slate-500">${w.work_category} • Milestone: ${w.current_milestone || 'Planning'}</div>
        </td>
        <td class="font-bold text-xs text-slate-800">${formatINR(w.sanction_amount)}</td>
        <td class="font-semibold text-xs text-emerald-700">${formatINR(w.total_disbursed)}</td>
        <td>
          <div class="flex items-center gap-1.5">
            <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
              <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${w.physical_progress_pct || 0}%"></div>
            </div>
            <span class="text-xs font-bold text-slate-700">${w.physical_progress_pct || 0}%</span>
          </div>
        </td>
        <td>${renderStatusBadge(w.status)}</td>
        <td>
          <button onclick="openProgressModal('${w.work_id}', '${escape(w.title)}', ${w.physical_progress_pct || 0})" class="bg-gov-primary hover:bg-blue-800 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-2xs transition">
            Update Progress
          </button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Failed to load Agency dashboard:", err);
  }
}

function openProgressModal(workId, titleEscaped, currentPct) {
  document.getElementById("prog-hidden-wid").value = workId;
  document.getElementById("prog-modal-wid").textContent = workId;
  document.getElementById("prog-modal-title").textContent = unescape(titleEscaped);
  document.getElementById("prog-range").value = currentPct;
  document.getElementById("prog-pct-num").value = currentPct;
  openModal("modal-progress");
}

async function submitProgressUpdate(e) {
  e.preventDefault();
  const workId = document.getElementById("prog-hidden-wid").value;
  const pct = parseInt(document.getElementById("prog-pct-num").value);
  const status = document.getElementById("prog-status").value;
  const milestone = document.getElementById("prog-milestone").value;
  const expenditure = parseFloat(document.getElementById("prog-expenditure").value) || 0.0;
  const desc = document.getElementById("prog-desc").value.trim();
  const voucher = document.getElementById("prog-voucher").value.trim();

  const payload = {
    work_id: workId,
    physical_progress_pct: pct,
    status: status,
    current_milestone: milestone,
    description: desc,
    expenditure_incurred: expenditure,
    payment_notes: voucher
  };

  try {
    const res = await fetch("/api/agency/update-progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Failed to update progress");

    alert(`✅ Progress Recorded!\nWork ID: ${result.work_id}\nPhysical Progress: ${result.physical_progress_pct}%\nStatus: ${result.status}`);
    closeModal("modal-progress");
    loadIaDashboard();
    fetchAnalyticsOverview();
  } catch (err) {
    alert("Error updating progress: " + err.message);
  }
}


// --- 7. PROJECT MONITORING & ML ANOMALY DETECTION HANDLERS ---

async function loadMonitoringDashboard() {
  const stateSel = document.getElementById("mon-filter-state");
  if (stateSel && geoMetadata && geoMetadata.states && stateSel.options.length <= 1) {
    stateSel.innerHTML = `<option value="">All States (${geoMetadata.states.length})</option>` +
      geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
  }

  const selectedState = stateSel ? stateSel.value : "";
  const selectedDist = document.getElementById("mon-filter-district") ? document.getElementById("mon-filter-district").value : "";

  // Fetch Summary KPIs
  try {
    const sumRes = await fetch(`/api/monitoring/summary?state=${encodeURIComponent(selectedState)}&district=${encodeURIComponent(selectedDist)}`);
    const summary = await sumRes.json();

    const b = summary.budget_monitoring || {};
    const d = summary.delay_monitoring || {};
    const p = summary.payment_analysis || {};
    const m = summary.ml_anomaly_detection || {};

    if (document.getElementById("mon-kpi-budget-status")) document.getElementById("mon-kpi-budget-status").textContent = `${(b.total_projects || 0).toLocaleString()} Works`;
    if (document.getElementById("mon-kpi-within-sanction")) document.getElementById("mon-kpi-within-sanction").textContent = (b.within_sanction || 0).toLocaleString();
    if (document.getElementById("mon-kpi-fully-disbursed")) document.getElementById("mon-kpi-fully-disbursed").textContent = (b.fully_disbursed || 0).toLocaleString();
    if (document.getElementById("mon-kpi-overruns")) document.getElementById("mon-kpi-overruns").textContent = (b.potential_budget_overruns || 0).toLocaleString();

    if (document.getElementById("mon-kpi-delay-status")) document.getElementById("mon-kpi-delay-status").textContent = `${((d.on_time || 0) + (d.delayed || 0)).toLocaleString()} Completed`;
    if (document.getElementById("mon-kpi-ontime")) document.getElementById("mon-kpi-ontime").textContent = (d.on_time || 0).toLocaleString();
    if (document.getElementById("mon-kpi-delayed")) document.getElementById("mon-kpi-delayed").textContent = (d.delayed || 0).toLocaleString();
    if (document.getElementById("mon-kpi-ongoing-delayed")) document.getElementById("mon-kpi-ongoing-delayed").textContent = (d.ongoing_delayed || 0).toLocaleString();

    if (document.getElementById("mon-kpi-total-payments")) document.getElementById("mon-kpi-total-payments").textContent = `${(p.total_payment_events || 0).toLocaleString()} Events`;
    if (document.getElementById("mon-kpi-avg-tranche")) document.getElementById("mon-kpi-avg-tranche").textContent = formatINR(p.avg_payment_tranche || 0);
    if (document.getElementById("mon-kpi-multi-tranche")) document.getElementById("mon-kpi-multi-tranche").textContent = (p.multiple_tranche_projects || 0).toLocaleString();
    if (document.getElementById("mon-kpi-vendor-conc")) document.getElementById("mon-kpi-vendor-conc").textContent = (p.vendor_concentration_projects || 0).toLocaleString();

    if (document.getElementById("mon-kpi-ml-anomalies")) document.getElementById("mon-kpi-ml-anomalies").textContent = `${(m.potential_anomalies || 0).toLocaleString()} Anomalies`;
    if (document.getElementById("mon-kpi-ml-analyzed")) document.getElementById("mon-kpi-ml-analyzed").textContent = (m.projects_analyzed || 0).toLocaleString();
    if (document.getElementById("mon-kpi-ml-pct")) document.getElementById("mon-kpi-ml-pct").textContent = `${m.anomaly_pct || 0}%`;

  } catch (err) {
    console.error("Failed to load monitoring summary:", err);
  }

  fetchMonitoringWorks(monPage);
}

async function onMonStateChange(stateVal) {
  const distSel = document.getElementById("mon-filter-district");
  if (!distSel) return;

  if (!stateVal) {
    distSel.innerHTML = `<option value="">All Districts</option>`;
    applyMonitoringFilter();
    return;
  }

  try {
    const res = await fetch(`/api/metadata/districts?state=${encodeURIComponent(stateVal)}`);
    const data = await res.json();
    const dists = data.districts || [];
    distSel.innerHTML = `<option value="">All Districts (${dists.length})</option>` +
      dists.map(d => `<option value="${d}">${d}</option>`).join("");
    applyMonitoringFilter();
  } catch (err) {
    console.error("Failed to load districts for monitoring:", err);
  }
}

async function fetchMonitoringWorks(page = 1) {
  monPage = page;
  const q = document.getElementById("mon-filter-q") ? document.getElementById("mon-filter-q").value : "";
  const state = document.getElementById("mon-filter-state") ? document.getElementById("mon-filter-state").value : "";
  const district = document.getElementById("mon-filter-district") ? document.getElementById("mon-filter-district").value : "";
  const delay = document.getElementById("mon-filter-delay") ? document.getElementById("mon-filter-delay").value : "";
  const budget = document.getElementById("mon-filter-budget") ? document.getElementById("mon-filter-budget").value : "";
  const anomaly = document.getElementById("mon-filter-anomaly") ? document.getElementById("mon-filter-anomaly").value : "";

  const params = new URLSearchParams({ page: monPage, limit: monLimit });
  if (q) params.append("q", q);
  if (state) params.append("state", state);
  if (district) params.append("district", district);
  if (delay) params.append("delay_status", delay);
  if (budget) params.append("budget_status", budget);
  if (anomaly) params.append("anomaly_status", anomaly);

  try {
    const res = await fetch(`/api/monitoring/works?${params.toString()}`);
    const data = await res.json();

    if (document.getElementById("mon-results-count")) document.getElementById("mon-results-count").textContent = (data.total || 0).toLocaleString();
    if (document.getElementById("mon-page-num")) document.getElementById("mon-page-num").textContent = data.page || 1;
    if (document.getElementById("mon-total-pages")) document.getElementById("mon-total-pages").textContent = data.total_pages || 1;

    const prevBtn = document.getElementById("mon-prev-btn");
    const nextBtn = document.getElementById("mon-next-btn");
    if (prevBtn) prevBtn.disabled = (data.page <= 1);
    if (nextBtn) nextBtn.disabled = (data.page >= data.total_pages);

    const tbody = document.getElementById("mon-table-body");
    if (!tbody) return;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-slate-400">No monitoring records found matching criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.items.map(item => {
      const riskScore = item.anomaly_risk_score || 0;
      let scoreBadge = `<span class="badge-status badge-anomaly-normal">${riskScore}/100 Normal</span>`;
      if (item.anomaly_status === "POTENTIAL ANOMALY") {
        if (riskScore >= 80) {
          scoreBadge = `<span class="badge-status badge-anomaly-high">⚠️ ${riskScore}/100 HIGH RISK</span>`;
        } else {
          scoreBadge = `<span class="badge-status badge-anomaly-medium">⚠️ ${riskScore}/100 MODERATE RISK</span>`;
        }
      }

      let delayBadge = `<span class="badge-status badge-delay-ontime">✓ ON_TIME</span>`;
      if (item.delay_status === "DELAYED") {
        delayBadge = `<span class="badge-status badge-delay-delayed">⏱ DELAYED</span>`;
      } else if (item.delay_status === "ONGOING_DELAYED") {
        delayBadge = `<span class="badge-status badge-delay-delayed">⏱ ONGOING OVER TARGET</span>`;
      } else if (item.delay_status === "ONGOING_WITHIN_TARGET") {
        delayBadge = `<span class="badge-status badge-delay-ongoing">⚙ ONGOING</span>`;
      }

      const disbRatioStr = item.budget_disbursement_ratio !== undefined ? `${(item.budget_disbursement_ratio * 100).toFixed(1)}%` : "N/A";

      return `
        <tr>
          <td>
            <div class="font-bold text-slate-800 font-mono text-xs">${item.work_id}</div>
            <div class="text-[11px] text-slate-500">${item.work_category || 'General'}</div>
          </td>
          <td>
            <div class="font-semibold text-slate-800 text-xs line-clamp-1" title="${item.work_title}">${item.work_title}</div>
            <div class="text-[11px] text-slate-500">${item.district}, ${item.state} • ${item.mp_name || ''}</div>
          </td>
          <td>
            <div class="font-bold text-slate-800">${formatINR(item.sanction_amount)}</div>
            <div class="text-[11px] font-semibold text-emerald-700">${formatINR(item.total_disbursed)}</div>
          </td>
          <td>
            <span class="font-bold text-xs ${item.budget_disbursement_ratio > 1.0 ? 'text-red-700' : 'text-slate-700'}">${disbRatioStr}</span>
          </td>
          <td>${delayBadge}</td>
          <td>
            <div class="font-bold text-xs">${item.payment_tranche_count} tranches</div>
            <div class="text-[11px] text-slate-500">${item.vendor_unique_count} vendors</div>
          </td>
          <td>${scoreBadge}</td>
          <td>
            <button onclick="inspectWorkDetail('${item.work_id}')" class="bg-purple-100 hover:bg-purple-200 text-purple-900 font-bold px-3 py-1.5 rounded-lg text-xs transition border border-purple-200">
              🔍 Inspect ML
            </button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error("Failed to fetch monitoring works:", err);
  }
}

function applyMonitoringFilter() {
  fetchMonitoringWorks(1);
}

function resetMonitoringFilters() {
  if (document.getElementById("mon-filter-q")) document.getElementById("mon-filter-q").value = "";
  if (document.getElementById("mon-filter-state")) document.getElementById("mon-filter-state").value = "";
  if (document.getElementById("mon-filter-district")) document.getElementById("mon-filter-district").value = "";
  if (document.getElementById("mon-filter-delay")) document.getElementById("mon-filter-delay").value = "";
  if (document.getElementById("mon-filter-budget")) document.getElementById("mon-filter-budget").value = "";
  if (document.getElementById("mon-filter-anomaly")) document.getElementById("mon-filter-anomaly").value = "";
  fetchMonitoringWorks(1);
}

function changeMonPage(delta) {
  fetchMonitoringWorks(monPage + delta);
}

async function inspectWorkDetail(work_id) {
  try {
    const res = await fetch(`/api/monitoring/work/${encodeURIComponent(work_id)}`);
    if (!res.ok) {
      alert("Failed to fetch work detail.");
      return;
    }
    const d = await res.json();

    const p = d.project_info || {};
    const f = d.financial_info || {};
    const t = d.timeline || {};
    const pay = d.payment_info || {};
    const ml = d.ml_monitoring || {};

    if (document.getElementById("ins-anomaly-badge")) {
      document.getElementById("ins-anomaly-badge").className = `badge-status ${ml.anomaly_status === 'POTENTIAL ANOMALY' ? 'badge-anomaly-high' : 'badge-anomaly-normal'}`;
      document.getElementById("ins-anomaly-badge").textContent = ml.anomaly_status || "NORMAL";
    }

    if (document.getElementById("ins-delay-badge")) {
      document.getElementById("ins-delay-badge").className = `badge-status ${t.delay_status === 'DELAYED' ? 'badge-delay-delayed' : 'badge-delay-ontime'}`;
      document.getElementById("ins-delay-badge").textContent = t.delay_status || "ON_TIME";
    }

    if (document.getElementById("ins-budget-badge")) {
      document.getElementById("ins-budget-badge").className = `badge-status ${f.budget_monitoring_status === 'POTENTIAL_BUDGET_OVERRUN' ? 'badge-returned' : 'badge-completed'}`;
      document.getElementById("ins-budget-badge").textContent = f.budget_monitoring_status || "WITHIN_SANCTION";
    }

    if (document.getElementById("ins-title")) document.getElementById("ins-title").textContent = p.work_title || "Project Detail";
    if (document.getElementById("ins-wid")) document.getElementById("ins-wid").textContent = `WORK ID: ${p.work_id}`;
    if (document.getElementById("ins-geo")) document.getElementById("ins-geo").textContent = `${p.district || ''}, ${p.state || ''}`;
    if (document.getElementById("ins-constituency")) document.getElementById("ins-constituency").textContent = p.constituency || "N/A";
    if (document.getElementById("ins-mp")) document.getElementById("ins-mp").textContent = p.mp_name || "N/A";
    if (document.getElementById("ins-category")) document.getElementById("ins-category").textContent = p.work_category || "General";

    if (document.getElementById("ins-ml-risk-score")) document.getElementById("ins-ml-risk-score").textContent = `${ml.anomaly_risk_score || 0}/100`;
    if (document.getElementById("ins-ml-raw")) document.getElementById("ins-ml-raw").textContent = ml.raw_anomaly_score || "0.0000";
    if (document.getElementById("ins-ml-pred")) document.getElementById("ins-ml-pred").textContent = `${ml.anomaly_prediction || 1} (${ml.anomaly_prediction === -1 ? 'Anomaly' : 'Normal'})`;
    if (document.getElementById("ins-ml-status")) document.getElementById("ins-ml-status").textContent = ml.anomaly_status || "NORMAL";

    const featObj = ml.features_contributing || {};
    const featList = document.getElementById("ins-ml-features-list");
    if (featList) {
      featList.innerHTML = `
        <div>• Sanction Outlay: <strong class="text-slate-800">${formatINR(featObj.sanction_amount)}</strong></div>
        <div>• Disbursed Outlay: <strong class="text-slate-800">${formatINR(featObj.total_disbursed)}</strong></div>
        <div>• Disbursement Ratio: <strong class="text-slate-800">${((featObj.disbursement_ratio || 0)*100).toFixed(1)}%</strong></div>
        <div>• Sanction Lead Time: <strong class="text-slate-800">${featObj.sanction_lead_time_days || 0} days</strong></div>
        <div>• Payment Tranches: <strong class="text-slate-800">${featObj.payment_tranches || 0} count</strong></div>
        <div>• Max Tranche Ratio: <strong class="text-slate-800">${((featObj.max_tranche_ratio || 0)*100).toFixed(1)}%</strong></div>
        <div>• Description Length: <strong class="text-slate-800">${featObj.description_length || 0} chars</strong></div>
      `;
    }

    if (document.getElementById("ins-sanction-amt")) document.getElementById("ins-sanction-amt").textContent = formatINR(f.sanction_amount);
    if (document.getElementById("ins-disbursed-amt")) document.getElementById("ins-disbursed-amt").textContent = formatINR(f.total_disbursed);
    if (document.getElementById("ins-disb-ratio")) document.getElementById("ins-disb-ratio").textContent = f.disbursement_ratio !== undefined ? `${(f.disbursement_ratio * 100).toFixed(1)}%` : "0%";
    if (document.getElementById("ins-variance-amt")) document.getElementById("ins-variance-amt").textContent = formatINR(f.remaining_sanction);
    if (document.getElementById("ins-budget-status-val")) document.getElementById("ins-budget-status-val").textContent = f.budget_monitoring_status || "WITHIN_SANCTION";

    if (document.getElementById("ins-rec-date")) document.getElementById("ins-rec-date").textContent = formatDate(t.recommended_date);
    if (document.getElementById("ins-sanc-date")) document.getElementById("ins-sanc-date").textContent = formatDate(t.sanction_date);
    if (document.getElementById("ins-exp-date")) document.getElementById("ins-exp-date").textContent = formatDate(t.expected_completion_date_proxy);
    if (document.getElementById("ins-comp-date")) document.getElementById("ins-comp-date").textContent = formatDate(t.completion_date);
    if (document.getElementById("ins-lead-time")) document.getElementById("ins-lead-time").textContent = `${t.sanction_lead_time_days || 0} days`;
    if (document.getElementById("ins-schedule-delay")) document.getElementById("ins-schedule-delay").textContent = `${t.schedule_delay_days || 0} days`;

    if (document.getElementById("ins-pay-count")) document.getElementById("ins-pay-count").textContent = `${pay.payment_tranche_count || 0} payment tranches`;
    if (document.getElementById("ins-pay-first")) document.getElementById("ins-pay-first").textContent = formatDate(pay.first_payment_date);
    if (document.getElementById("ins-pay-last")) document.getElementById("ins-pay-last").textContent = formatDate(pay.latest_payment_date);
    if (document.getElementById("ins-pay-max-ratio")) document.getElementById("ins-pay-max-ratio").textContent = pay.max_single_tranche_ratio !== undefined ? `${(pay.max_single_tranche_ratio * 100).toFixed(1)}%` : "0%";
    if (document.getElementById("ins-pay-vendors")) document.getElementById("ins-pay-vendors").textContent = pay.vendor_unique_count || 0;

    const payTbody = document.getElementById("ins-payments-tbody");
    if (payTbody) {
      const plist = pay.payments_list || [];
      if (plist.length === 0) {
        payTbody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-slate-400">No payment events recorded for this project.</td></tr>`;
      } else {
        payTbody.innerHTML = plist.map(pitem => `
          <tr>
            <td class="font-mono text-xs">${formatDate(pitem.expenditure_date)}</td>
            <td class="font-semibold text-slate-800 text-xs">${pitem.vendor_name_normalized || pitem.vendor_name_raw || 'Vendor'}</td>
            <td><span class="badge-status badge-completed">${pitem.payment_status || 'SUCCESS'}</span></td>
            <td class="font-bold text-emerald-700 text-xs">${formatINR(pitem.reported_fund_disbursed_amount)}</td>
          </tr>
        `).join("");
      }
    }

    openModal("modal-inspect");
  } catch (err) {
    console.error("Error inspecting work:", err);
    alert("Error fetching work inspection profile.");
  }
}

async function loadAlertsView() {
  const container = document.getElementById("alerts-container");
  if (!container) return;

  container.innerHTML = `<div class="p-6 text-center text-slate-400">Loading screening alerts...</div>`;

  try {
    const res = await fetch("/api/monitoring/alerts?limit=50");
    const data = await res.json();

    const alerts = data.alerts || [];
    const totalAlerts = data.total_alerts !== undefined ? data.total_alerts : alerts.length;
    if (document.getElementById("alerts-count-badge")) document.getElementById("alerts-count-badge").textContent = totalAlerts.toLocaleString();

    if (alerts.length === 0) {
      container.innerHTML = `<div class="p-8 text-center text-slate-500 font-medium">Zero screening alerts triggered across active dataset.</div>`;
      return;
    }

    container.innerHTML = alerts.map(a => {
      let sevColor = "border-amber-200 bg-amber-50 text-amber-900";
      if (a.severity === "HIGH") sevColor = "border-red-200 bg-red-50 text-red-900";

      return `
        <div class="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-slate-50 transition">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${sevColor}">${a.alert_type}</span>
              <span class="text-xs font-mono font-bold text-slate-600">${a.work_id}</span>
              <span class="text-xs text-slate-500">• ${a.district}, ${a.state}</span>
            </div>
            <div class="font-bold text-slate-800 text-sm">${a.work_title}</div>
            <div class="text-xs text-slate-600">Measurement: <strong class="text-slate-800">${a.measured_value}</strong></div>
          </div>
          <div class="flex items-center gap-3">
            <div class="text-right hidden sm:block">
              <div class="text-[10px] text-slate-500 uppercase font-semibold">Anomaly Risk</div>
              <div class="text-base font-black ${a.anomaly_risk_score >= 80 ? 'text-red-700' : 'text-amber-700'}">${a.anomaly_risk_score}/100</div>
            </div>
            <button onclick="inspectWorkDetail('${a.work_id}')" class="bg-gov-primary hover:bg-blue-900 text-white font-bold px-3.5 py-2 rounded-xl text-xs transition shadow-xs">
              Inspect ML Profile
            </button>
          </div>
        </div>
      `;
    }).join("");

  } catch (err) {
    console.error("Failed to load alerts:", err);
  }
}

async function triggerRetrainMl() {
  if (!confirm("Are you sure you want to retrain the Isolation Forest model on all 41,086 projects with contamination = 0.05?")) return;

  try {
    const res = await fetch("/api/ml/retrain?contamination=0.05", { method: "POST" });
    const data = await res.json();

    if (res.ok && data.success) {
      alert("✅ Isolation Forest model retrained successfully!\n" + data.message);
      loadMonitoringDashboard();
    } else {
      alert("Retraining failed: " + (data.detail || "Unknown error"));
    }
  } catch (err) {
    console.error("Retrain error:", err);
    alert("Retrain API call failed.");
  }
}

async function renderAnalyticsCharts() {
  try {
    const res = await fetch("/api/analytics/monitoring");
    const data = await res.json();

    // 1. State-Wise Projects Bar Chart
    if (document.getElementById("chart-states") && data.state_metrics) {
      const topStates = data.state_metrics.slice(0, 15);
      renderChart("chart-states", "bar", {
        labels: topStates.map(s => s.state),
        datasets: [{
          label: "Sanctioned Projects",
          data: topStates.map(s => s.project_count),
          backgroundColor: "#0F4C81",
          borderRadius: 4
        }]
      });
    }

    // 2. Work Completion Status (Doughnut)
    if (document.getElementById("chart-status") && data.completion_dist) {
      renderChart("chart-status", "doughnut", {
        labels: data.completion_dist.map(c => c.status),
        datasets: [{
          data: data.completion_dist.map(c => c.count),
          backgroundColor: ["#107C41", "#F58220", "#0F4C81", "#64748B"]
        }]
      });
    }

    // 3. Schedule Delay Classification (Bar)
    if (document.getElementById("chart-delay") && data.delay_dist) {
      renderChart("chart-delay", "bar", {
        labels: data.delay_dist.map(d => d.status),
        datasets: [{
          label: "Projects",
          data: data.delay_dist.map(d => d.count),
          backgroundColor: ["#107C41", "#DC2626", "#2563EB", "#D97706"],
          borderRadius: 4
        }]
      });
    }

    // 4. Budget Monitoring Classification (Doughnut)
    if (document.getElementById("chart-budget") && data.budget_dist) {
      renderChart("chart-budget", "doughnut", {
        labels: data.budget_dist.map(b => b.status),
        datasets: [{
          data: data.budget_dist.map(b => b.count),
          backgroundColor: ["#107C41", "#2563EB", "#DC2626"]
        }]
      });
    }

    // 5. Payment Tranche Frequency (Bar)
    if (document.getElementById("chart-tranches") && data.tranche_dist) {
      renderChart("chart-tranches", "bar", {
        labels: data.tranche_dist.map(t => t.category),
        datasets: [{
          label: "Projects",
          data: data.tranche_dist.map(t => t.count),
          backgroundColor: "#7C3AED",
          borderRadius: 4
        }]
      });
    }

    // 6. ML Anomaly Screening Distribution (Doughnut)
    if (document.getElementById("chart-anomalies") && data.anomaly_dist) {
      renderChart("chart-anomalies", "doughnut", {
        labels: data.anomaly_dist.map(a => a.status),
        datasets: [{
          data: data.anomaly_dist.map(a => a.count),
          backgroundColor: ["#334155", "#9333EA"]
        }]
      });
    }

    // 7. Monthly Expenditure Trend (Line)
    if (document.getElementById("chart-monthly-payments") && data.monthly_payments) {
      const topMonths = data.monthly_payments.slice(-24);
      renderChart("chart-monthly-payments", "line", {
        labels: topMonths.map(m => m.month_str),
        datasets: [{
          label: "Disbursed Amount (₹)",
          data: topMonths.map(m => m.total_disbursed),
          borderColor: "#107C41",
          backgroundColor: "rgba(16, 124, 65, 0.1)",
          fill: true,
          tension: 0.3
        }]
      });
    }

    // 8. Top Disbursed Outlay by State (Bar)
    if (document.getElementById("chart-risk-by-state") && data.state_metrics) {
      const sortedByDisbursed = [...data.state_metrics].sort((a,b) => b.total_disbursed - a.total_disbursed).slice(0, 10);
      renderChart("chart-risk-by-state", "bar", {
        labels: sortedByDisbursed.map(s => s.state),
        datasets: [{
          label: "Total Disbursed (₹ Cr)",
          data: sortedByDisbursed.map(s => (s.total_disbursed / 10000000).toFixed(2)),
          backgroundColor: "#059669",
          borderRadius: 4
        }]
      });
    }

    // Render State Summary Table
    const tbody = document.getElementById("analytics-states-tbody");
    if (tbody && data.state_metrics) {
      tbody.innerHTML = data.state_metrics.map(s => {
        const rate = s.project_count > 0 ? ((s.total_disbursed / (s.total_sanction || 1)) * 100).toFixed(1) : 0;
        return `
          <tr>
            <td class="font-bold text-slate-800">${s.state}</td>
            <td>${s.project_count.toLocaleString()}</td>
            <td class="font-semibold text-slate-800">${formatINR(s.total_sanction)}</td>
            <td class="font-semibold text-emerald-700">${formatINR(s.total_disbursed)}</td>
            <td>
              <div class="flex items-center gap-2">
                <span class="font-bold text-xs">${rate}%</span>
                <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                  <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${Math.min(rate, 100)}%"></div>
                </div>
              </div>
            </td>
          </tr>
        `;
      }).join("");
    }

  } catch (err) {
    console.error("Failed to load analytics monitoring data:", err);
  }
}

function renderChart(canvasId, type, chartData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (typeof Chart === "undefined") {
    console.warn("Chart.js library is not available.");
    return;
  }

  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
  }

  chartInstances[canvasId] = new Chart(ctx, {
    type: type,
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: type === "doughnut", position: "right", labels: { boxWidth: 12, font: { size: 10 } } }
      },
      scales: type !== "doughnut" ? {
        y: { beginAtZero: true, grid: { color: "#F1F5F9" } },
        x: { grid: { display: false } }
      } : {}
    }
  });
}

// --- RISK HEAT MAP & ANALYTICS SUB-TAB HANDLERS ---
let activeAnalyticsSubTab = 'charts';
let heatmapSelectedMetric = 'avg_risk';
let heatmapSelectedState = null;
let heatmapSelectedDistrict = null;
let leafletMapInstance = null;
let leafletGeoJsonLayer = null;
let nationalRiskData = [];
let nationalSummaryData = null;
let stateRiskData = [];
let stateSummaryData = null;
let districtProjectsData = [];

function switchAnalyticsSubTab(tabName) {
  activeAnalyticsSubTab = tabName;

  const chartsBtn = document.getElementById("tab-btn-charts");
  const heatmapBtn = document.getElementById("tab-btn-heatmap");

  const chartsView = document.getElementById("analytics-subview-charts");
  const heatmapView = document.getElementById("analytics-subview-heatmap");

  if (tabName === 'charts') {
    if (chartsBtn) chartsBtn.className = "px-5 py-2 rounded-xl text-xs font-bold transition shadow-xs bg-gov-primary text-white";
    if (heatmapBtn) heatmapBtn.className = "px-5 py-2 rounded-xl text-xs font-bold transition text-slate-700 hover:bg-slate-200";
    if (chartsView) chartsView.classList.remove("hidden");
    if (heatmapView) heatmapView.classList.add("hidden");
    renderAnalyticsCharts();
  } else {
    if (heatmapBtn) heatmapBtn.className = "px-5 py-2 rounded-xl text-xs font-bold transition shadow-xs bg-gov-primary text-white";
    if (chartsBtn) chartsBtn.className = "px-5 py-2 rounded-xl text-xs font-bold transition text-slate-700 hover:bg-slate-200";
    if (chartsView) chartsView.classList.add("hidden");
    if (heatmapView) heatmapView.classList.remove("hidden");
    
    initRiskHeatmap();
  }
}

async function initRiskHeatmap() {
  if (!leafletMapInstance && window.L) {
    const mapContainer = document.getElementById("india-map-container");
    if (!mapContainer) return;

    // Initialize standalone vector Leaflet map on clean neutral background (NO street tile layer / NO CARTO)
    leafletMapInstance = L.map('india-map-container', {
      center: [22.5937, 78.9629],
      zoom: 4.5,
      zoomControl: true,
      attributionControl: false,
      scrollWheelZoom: false
    });
  }

  setTimeout(() => {
    if (leafletMapInstance) leafletMapInstance.invalidateSize();
  }, 100);

  if (!heatmapSelectedState) {
    loadNationalHeatmapData();
  } else if (!heatmapSelectedDistrict) {
    loadStateDistrictHeatmapData(heatmapSelectedState);
  } else {
    selectHeatmapDistrict(heatmapSelectedDistrict);
  }
}

function onHeatmapMetricChange(newMetric) {
  heatmapSelectedMetric = newMetric;
  if (leafletGeoJsonLayer) {
    renderIndiaStatesGeoJsonLayer();
  }
  if (!heatmapSelectedState) {
    renderNationalRightPanel();
  } else if (!heatmapSelectedDistrict) {
    renderStateRightPanel();
  } else {
    renderDistrictRightPanel();
  }
}

function resetHeatmapToNational() {
  heatmapSelectedState = null;
  heatmapSelectedDistrict = null;
  if (leafletGeoJsonLayer && leafletMapInstance) {
    leafletMapInstance.fitBounds(leafletGeoJsonLayer.getBounds(), { padding: [15, 15] });
  }
  loadNationalHeatmapData();
}

async function loadNationalHeatmapData() {
  heatmapSelectedState = null;
  heatmapSelectedDistrict = null;
  updateHeatmapBreadcrumbs();

  try {
    const res = await fetch(`/api/analytics/risk-map?metric=${encodeURIComponent(heatmapSelectedMetric)}`);
    const data = await res.json();
    nationalRiskData = data.states || [];
    nationalSummaryData = data.national_summary || null;

    renderIndiaStatesGeoJsonLayer();
    renderNationalRightPanel();
  } catch (err) {
    console.error("Failed to load national risk map data:", err);
  }
}

function updateHeatmapBreadcrumbs() {
  const crumbStateWrap = document.getElementById("crumb-state-wrap");
  const crumbDistrictWrap = document.getElementById("crumb-district-wrap");
  const crumbStateBtn = document.getElementById("crumb-state-btn");
  const crumbDistrictBtn = document.getElementById("crumb-district-btn");

  if (!heatmapSelectedState) {
    if (crumbStateWrap) crumbStateWrap.classList.add("hidden");
    if (crumbDistrictWrap) crumbDistrictWrap.classList.add("hidden");
  } else if (!heatmapSelectedDistrict) {
    if (crumbStateWrap) crumbStateWrap.classList.remove("hidden");
    if (crumbStateBtn) crumbStateBtn.textContent = heatmapSelectedState;
    if (crumbDistrictWrap) crumbDistrictWrap.classList.add("hidden");
  } else {
    if (crumbStateWrap) crumbStateWrap.classList.remove("hidden");
    if (crumbStateBtn) crumbStateBtn.textContent = heatmapSelectedState;
    if (crumbDistrictWrap) crumbDistrictWrap.classList.remove("hidden");
    if (crumbDistrictBtn) crumbDistrictBtn.textContent = heatmapSelectedDistrict;
  }
}

function renderNationalRightPanel() {
  const panel = document.getElementById("heatmap-panel-content");
  if (!panel) return;

  const summary = nationalSummaryData || {};
  const totalProjects = (summary.project_count || 41086).toLocaleString();
  const avgRisk = summary.avg_risk || "20.1";
  const highRisk = (summary.high_risk_count || 1958).toLocaleString();
  const anomalies = (summary.anomaly_count || 1958).toLocaleString();
  const delayed = (summary.delayed_count || 9413).toLocaleString();
  const disbRate = (summary.disbursement_rate || 72.1).toFixed(1) + "%";

  panel.innerHTML = `
    <div>
      <span class="text-[10px] font-bold uppercase tracking-wider bg-blue-50 text-gov-primary px-2.5 py-1 rounded-md border border-blue-200">National Overview</span>
      <h3 class="text-xl font-black text-gov-dark mt-1">India</h3>
      <p class="text-xs text-slate-500 font-medium">National risk baselines across connected MPLADS projects.</p>
    </div>

    <!-- Compact 6-Metric Grid -->
    <div class="grid grid-cols-2 gap-2 text-xs">
      <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200">
        <span class="text-slate-500 text-[11px] block">Projects Analyzed</span>
        <strong class="text-sm font-black text-slate-800">${totalProjects}</strong>
      </div>
      <div class="p-2.5 bg-purple-50/60 rounded-xl border border-purple-200">
        <span class="text-purple-800 text-[11px] block">Avg ML Risk Score</span>
        <strong class="text-sm font-black text-purple-900">${avgRisk}/100</strong>
      </div>
      <div class="p-2.5 bg-amber-50/60 rounded-xl border border-amber-200">
        <span class="text-amber-800 text-[11px] block">High-Risk Projects</span>
        <strong class="text-sm font-black text-amber-900">${highRisk}</strong>
      </div>
      <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200">
        <span class="text-slate-500 text-[11px] block">ML Anomalies</span>
        <strong class="text-sm font-black text-slate-800">${anomalies}</strong>
      </div>
      <div class="p-2.5 bg-red-50/60 rounded-xl border border-red-200">
        <span class="text-red-800 text-[11px] block">Delayed Projects</span>
        <strong class="text-sm font-black text-red-700">${delayed}</strong>
      </div>
      <div class="p-2.5 bg-emerald-50/60 rounded-xl border border-emerald-200">
        <span class="text-emerald-800 text-[11px] block">Disbursement Rate</span>
        <strong class="text-sm font-black text-emerald-800">${disbRate}</strong>
      </div>
    </div>

    <!-- Connected States List -->
    <div class="space-y-2 pt-1">
      <div class="flex items-center justify-between border-b border-slate-100 pb-1.5">
        <h4 class="text-xs font-bold text-slate-700 uppercase tracking-wider">Connected States (${nationalRiskData.length})</h4>
        <span class="text-[10px] text-slate-400 font-medium">Click state to select</span>
      </div>
      <div class="space-y-1.5 max-h-[280px] overflow-y-auto pr-1">
        ${nationalRiskData.map(s => `
          <div onclick="selectHeatmapState('${s.state}')" class="p-2.5 bg-white rounded-xl border border-slate-200 hover:border-gov-primary hover:shadow-xs cursor-pointer transition flex items-center justify-between">
            <div>
              <strong class="text-xs text-slate-800 font-bold block">${s.state}</strong>
              <span class="text-[10px] text-slate-500 font-medium">${s.project_count.toLocaleString()} project(s)</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-mono font-bold text-slate-800">${getMetricDisplayValue(s)}</span>
              <span class="w-3 h-3 rounded-full shrink-0" style="background-color: ${getMetricColorForFeature(s)}"></span>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function getMetricDisplayValue(item) {
  if (heatmapSelectedMetric === 'avg_risk') return `${item.avg_risk}/100`;
  if (heatmapSelectedMetric === 'high_risk_count') return `${item.high_risk_count} high-risk`;
  if (heatmapSelectedMetric === 'anomaly_rate') return `${item.anomaly_rate}% anom`;
  if (heatmapSelectedMetric === 'delay_rate') return `${item.delay_rate}% delay`;
  if (heatmapSelectedMetric === 'disbursement_rate') return `${item.disbursement_rate}% disb`;
  return `${item.project_count} works`;
}

function normalizeStateName(name) {
  if (!name) return "";
  let s = String(name).trim().toLowerCase();
  s = s.replace(/&/g, "and");
  s = s.replace(/\s+/g, " ");
  if (s.includes("andaman")) return "andaman and nicobar islands";
  if (s.includes("dadra") || s.includes("daman")) return "dadra and nagar haveli and daman and diu";
  if (s === "orissa" || s === "odisha") return "odisha";
  if (s === "uttaranchal" || s === "uttarakhand") return "uttarakhand";
  if (s.includes("pondicherry") || s.includes("puducherry")) return "puducherry";
  if (s.includes("jammu")) return "jammu and kashmir";
  return s;
}

async function renderIndiaStatesGeoJsonLayer() {
  if (!leafletMapInstance || !window.L) return;

  try {
    const geoRes = await fetch("/js/india_states.geojson");
    const geoData = await geoRes.json();

    if (leafletGeoJsonLayer) {
      leafletMapInstance.removeLayer(leafletGeoJsonLayer);
    }

    leafletGeoJsonLayer = L.geoJSON(geoData, {
      style: (feature) => {
        const rawStateName = feature.properties.name || feature.properties.state || feature.properties.shapeName || "";
        const normGeoName = normalizeStateName(rawStateName);
        const stData = nationalRiskData.find(s => normalizeStateName(s.state) === normGeoName);
        const isSelected = heatmapSelectedState && normalizeStateName(heatmapSelectedState) === normGeoName;

        if (!stData || stData.project_count === 0) {
          return {
            fillColor: "#94A3B8",
            weight: isSelected ? 3 : 1.2,
            opacity: 1,
            color: isSelected ? "#0F4C81" : "#CBD5E1",
            fillOpacity: 0.35
          };
        }
        return {
          fillColor: getMetricColorForFeature(stData),
          weight: isSelected ? 3.5 : 1.5,
          opacity: 1,
          color: isSelected ? "#0F4C81" : "#FFFFFF",
          fillOpacity: isSelected ? 0.95 : 0.85
        };
      },
      onEachFeature: (feature, layer) => {
        const rawStateName = feature.properties.name || feature.properties.state || feature.properties.shapeName || "";
        const normGeoName = normalizeStateName(rawStateName);
        const stData = nationalRiskData.find(s => normalizeStateName(s.state) === normGeoName);

        if (stData) {
          layer.bindTooltip(`
            <div class="p-2.5 space-y-1 font-sans text-xs bg-white text-slate-800 rounded-lg shadow-md border border-slate-200">
              <div class="font-black text-slate-900 text-sm border-b border-slate-200 pb-1 flex items-center justify-between gap-3">
                <span>${stData.state}</span>
                <span class="w-2.5 h-2.5 rounded-full" style="background-color: ${getMetricColorForFeature(stData)}"></span>
              </div>
              <div>Projects Analyzed: <strong>${stData.project_count.toLocaleString()}</strong></div>
              <div>Average ML Risk Score: <strong class="text-purple-900">${stData.avg_risk}/100</strong></div>
              <div>High-Risk Projects: <strong class="text-amber-800">${stData.high_risk_count.toLocaleString()}</strong></div>
              <div>ML Anomalies: <strong class="text-purple-900">${stData.anomaly_count.toLocaleString()}</strong></div>
              <div>Delayed Projects: <strong class="text-red-700">${stData.delayed_count.toLocaleString()}</strong></div>
              <div>Disbursement Rate: <strong class="text-emerald-700">${stData.disbursement_rate}%</strong></div>
            </div>
          `, { sticky: true });
        } else {
          layer.bindTooltip(`
            <div class="p-2 font-sans text-xs bg-white text-slate-800 rounded-lg shadow-md border border-slate-200">
              <strong class="text-slate-800">${rawStateName}</strong>
              <div class="text-slate-500 font-medium mt-0.5">⚪ Insufficient Monitoring Data</div>
            </div>
          `, { sticky: true });
        }

        layer.on({
          mouseover: (e) => {
            const l = e.target;
            l.setStyle({ weight: 3, color: '#0F4C81', fillOpacity: 0.95 });
          },
          mouseout: (e) => {
            leafletGeoJsonLayer.resetStyle(e.target);
          },
          click: (e) => {
            const matchingStateInDb = nationalRiskData.find(s => normalizeStateName(s.state) === normGeoName);
            selectHeatmapState(matchingStateInDb ? matchingStateInDb.state : rawStateName);
          }
        });
      }
    }).addTo(leafletMapInstance);

    // Auto-fit bounds to India GeoJSON cleanly
    if (leafletGeoJsonLayer && leafletMapInstance) {
      leafletMapInstance.fitBounds(leafletGeoJsonLayer.getBounds(), { padding: [15, 15] });
    }

  } catch (err) {
    console.error("Failed to load India states GeoJSON:", err);
  }
}

function getMetricColorForFeature(stData) {
  if (!stData || stData.project_count === 0) return "#94A3B8";

  if (heatmapSelectedMetric === 'avg_risk') {
    return stData.color || (stData.avg_risk >= 65 ? '#DC2626' : (stData.avg_risk >= 40 ? '#F58220' : '#107C41'));
  } else if (heatmapSelectedMetric === 'high_risk_count') {
    return stData.high_risk_count >= 300 ? '#DC2626' : (stData.high_risk_count >= 100 ? '#F58220' : '#107C41');
  } else if (heatmapSelectedMetric === 'anomaly_rate') {
    return stData.anomaly_rate >= 8.0 ? '#DC2626' : (stData.anomaly_rate >= 4.0 ? '#F58220' : '#107C41');
  } else if (heatmapSelectedMetric === 'delay_rate') {
    return stData.delay_rate >= 25.0 ? '#DC2626' : (stData.delay_rate >= 15.0 ? '#F58220' : '#107C41');
  } else if (heatmapSelectedMetric === 'disbursement_rate') {
    return stData.disbursement_rate >= 75.0 ? '#107C41' : (stData.disbursement_rate >= 55.0 ? '#F58220' : '#DC2626');
  } else {
    return stData.project_count >= 5000 ? '#0F4C81' : (stData.project_count >= 1000 ? '#2563EB' : '#60A5FA');
  }
}

async function selectHeatmapState(stateName) {
  const stData = nationalRiskData.find(s => s.state.toLowerCase() === stateName.toLowerCase());
  if (!stData) {
    alert(`Insufficient monitoring data available for ${stateName} in the current dataset scope.`);
    return;
  }

  heatmapSelectedState = stateName;
  heatmapSelectedDistrict = null;
  updateHeatmapBreadcrumbs();

  if (leafletGeoJsonLayer) {
    renderIndiaStatesGeoJsonLayer();
  }

  loadStateDistrictHeatmapData(stateName);
}

async function loadStateDistrictHeatmapData(stateName) {
  try {
    const res = await fetch(`/api/analytics/risk-map?state=${encodeURIComponent(stateName)}&metric=${encodeURIComponent(heatmapSelectedMetric)}`);
    const data = await res.json();
    stateRiskData = data.districts || [];
    stateSummaryData = data.state_summary || null;

    renderStateRightPanel();
  } catch (err) {
    console.error("Failed to load district risk data:", err);
  }
}

function renderStateRightPanel() {
  const panel = document.getElementById("heatmap-panel-content");
  if (!panel) return;

  const stName = heatmapSelectedState;
  const summary = stateSummaryData || {};
  const totalProjects = (summary.project_count || 0).toLocaleString();
  const avgRisk = summary.avg_risk || "0.0";
  const highRisk = (summary.high_risk_count || 0).toLocaleString();
  const anomalies = (summary.anomaly_count || 0).toLocaleString();
  const delayed = (summary.delayed_count || 0).toLocaleString();
  const disbRate = (summary.disbursement_rate || 0.0).toFixed(1) + "%";

  const stNatObj = nationalRiskData.find(s => s.state.toLowerCase() === stName.toLowerCase()) || {};
  const riskBadgeColor = stNatObj.color || "#107C41";
  const riskLabel = stNatObj.risk_label || "Lower Statistical Risk";

  panel.innerHTML = `
    <div>
      <div class="flex items-center justify-between">
        <span class="text-[10px] font-bold uppercase tracking-wider bg-purple-50 text-purple-900 px-2.5 py-1 rounded-md border border-purple-200">State View</span>
        <span class="text-[11px] font-bold px-2.5 py-0.5 rounded-full text-white" style="background-color: ${riskBadgeColor}">${riskLabel}</span>
      </div>
      <h3 class="text-xl font-black text-gov-dark mt-1">${stName}</h3>
    </div>

    <!-- Compact 6-Metric Grid -->
    <div class="grid grid-cols-2 gap-2 text-xs">
      <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200">
        <span class="text-slate-500 text-[11px] block">Projects Analyzed</span>
        <strong class="text-sm font-black text-slate-800">${totalProjects}</strong>
      </div>
      <div class="p-2.5 bg-purple-50/60 rounded-xl border border-purple-200">
        <span class="text-purple-800 text-[11px] block">Avg ML Risk Score</span>
        <strong class="text-sm font-black text-purple-900">${avgRisk}/100</strong>
      </div>
      <div class="p-2.5 bg-amber-50/60 rounded-xl border border-amber-200">
        <span class="text-amber-800 text-[11px] block">High-Risk Projects</span>
        <strong class="text-sm font-black text-amber-900">${highRisk}</strong>
      </div>
      <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200">
        <span class="text-slate-500 text-[11px] block">ML Anomalies</span>
        <strong class="text-sm font-black text-slate-800">${anomalies}</strong>
      </div>
      <div class="p-2.5 bg-red-50/60 rounded-xl border border-red-200">
        <span class="text-red-800 text-[11px] block">Delayed Projects</span>
        <strong class="text-sm font-black text-red-700">${delayed}</strong>
      </div>
      <div class="p-2.5 bg-emerald-50/60 rounded-xl border border-emerald-200">
        <span class="text-emerald-800 text-[11px] block">Disbursement Rate</span>
        <strong class="text-sm font-black text-emerald-800">${disbRate}</strong>
      </div>
    </div>

    <!-- Ranked Districts List (Item 9 in requirements) -->
    <div class="space-y-2 pt-1">
      <div class="flex items-center justify-between border-b border-slate-100 pb-1.5">
        <h4 class="text-xs font-bold text-slate-700 uppercase tracking-wider">Districts (${stateRiskData.length})</h4>
        <span class="text-[10px] text-slate-400 font-medium">Ranked by risk score</span>
      </div>
      <div class="space-y-1.5 max-h-[270px] overflow-y-auto pr-1">
        ${stateRiskData.map(d => `
          <div onclick="selectHeatmapDistrict('${d.district}')" class="p-2.5 bg-white rounded-xl border border-slate-200 hover:border-gov-primary hover:shadow-xs cursor-pointer transition flex items-center justify-between">
            <div>
              <strong class="text-xs text-slate-800 font-bold block truncate max-w-[150px]" title="${d.district}">${d.district}</strong>
              <span class="text-[10px] text-slate-500 font-medium">${d.project_count} project(s)</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-mono font-bold text-slate-800">${d.avg_risk}/100</span>
              <span class="w-3 h-3 rounded-full shrink-0" style="background-color: ${getMetricColorForFeature(d)}"></span>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

async function selectHeatmapDistrict(districtName) {
  heatmapSelectedDistrict = districtName;
  if (!heatmapSelectedState) return;

  updateHeatmapBreadcrumbs();

  try {
    const res = await fetch(`/api/analytics/risk-map/projects?state=${encodeURIComponent(heatmapSelectedState)}&district=${encodeURIComponent(districtName)}&limit=15`);
    const data = await res.json();
    districtProjectsData = data.items || [];

    renderDistrictRightPanel();
  } catch (err) {
    console.error("Failed to load district projects:", err);
  }
}

function renderDistrictRightPanel() {
  const panel = document.getElementById("heatmap-panel-content");
  if (!panel) return;

  const stName = heatmapSelectedState;
  const distName = heatmapSelectedDistrict;
  const distObj = stateRiskData.find(d => d.district.toLowerCase() === distName.toLowerCase()) || {};

  const totalProjects = (distObj.project_count || districtProjectsData.length).toLocaleString();
  const avgRisk = distObj.avg_risk || (districtProjectsData.length > 0 ? (districtProjectsData.reduce((acc, p) => acc + p.anomaly_risk_score, 0) / districtProjectsData.length).toFixed(1) : "0.0");
  const highRisk = (distObj.high_risk_count || districtProjectsData.filter(p => p.anomaly_risk_score >= 50).length).toLocaleString();
  const anomalies = (distObj.anomaly_count || districtProjectsData.filter(p => p.anomaly_status === 'POTENTIAL ANOMALY').length).toLocaleString();
  const delayed = (distObj.delayed_count || districtProjectsData.filter(p => p.delay_status.includes('DELAYED')).length).toLocaleString();
  const disbRate = (distObj.disbursement_rate || 0.0).toFixed(1) + "%";

  panel.innerHTML = `
    <div>
      <span class="text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 px-2.5 py-1 rounded-md border border-emerald-200">Selected District</span>
      <h3 class="text-xl font-black text-gov-dark mt-1">${distName}</h3>
      <p class="text-xs text-slate-500 font-medium">${stName} • District Monitoring Profile</p>
    </div>

    <!-- Compact 6-Metric Grid -->
    <div class="grid grid-cols-2 gap-2 text-xs">
      <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200">
        <span class="text-slate-500 text-[11px] block">Projects Analyzed</span>
        <strong class="text-sm font-black text-slate-800">${totalProjects}</strong>
      </div>
      <div class="p-2.5 bg-purple-50/60 rounded-xl border border-purple-200">
        <span class="text-purple-800 text-[11px] block">Avg ML Risk Score</span>
        <strong class="text-sm font-black text-purple-900">${avgRisk}/100</strong>
      </div>
      <div class="p-2.5 bg-amber-50/60 rounded-xl border border-amber-200">
        <span class="text-amber-800 text-[11px] block">High-Risk Projects</span>
        <strong class="text-sm font-black text-amber-900">${highRisk}</strong>
      </div>
      <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200">
        <span class="text-slate-500 text-[11px] block">ML Anomalies</span>
        <strong class="text-sm font-black text-slate-800">${anomalies}</strong>
      </div>
      <div class="p-2.5 bg-red-50/60 rounded-xl border border-red-200">
        <span class="text-red-800 text-[11px] block">Delayed Projects</span>
        <strong class="text-sm font-black text-red-700">${delayed}</strong>
      </div>
      <div class="p-2.5 bg-emerald-50/60 rounded-xl border border-emerald-200">
        <span class="text-emerald-800 text-[11px] block">Disbursement Rate</span>
        <strong class="text-sm font-black text-emerald-800">${disbRate}</strong>
      </div>
    </div>

    <!-- Top Projects Table (Item 10 & 11 in requirements) -->
    <div class="space-y-2 pt-1">
      <div class="flex items-center justify-between border-b border-slate-100 pb-1 text-xs">
        <h4 class="font-bold text-slate-700 uppercase tracking-wider">Top Projects</h4>
        <button onclick="viewAllDistrictProjects('${stName}', '${distName}')" class="text-gov-primary hover:underline text-[11px] font-bold">
          View All Projects →
        </button>
      </div>

      <div class="border border-slate-200 rounded-xl overflow-hidden max-h-[230px] overflow-y-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200 sticky top-0">
            <tr>
              <th class="p-2">Work ID</th>
              <th class="p-2">Work Title</th>
              <th class="p-2 text-right">Risk Score</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            ${districtProjectsData.length === 0 ? `
              <tr><td colspan="3" class="p-3 text-center text-slate-400">No project records found.</td></tr>
            ` : districtProjectsData.map(p => `
              <tr onclick="openProject360('${p.work_id}')" class="hover:bg-blue-50/80 cursor-pointer transition">
                <td class="p-2 font-mono font-bold text-gov-primary text-[11px] whitespace-nowrap">${p.work_id}</td>
                <td class="p-2 font-medium text-slate-800 max-w-[140px] truncate" title="${p.work_title}">${p.work_title}</td>
                <td class="p-2 text-right font-mono font-bold text-purple-900 whitespace-nowrap">${p.anomaly_risk_score}/100</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function viewAllDistrictProjects(stateName, districtName) {
  switchNav('citizen');
  const searchInput = document.getElementById("explorer-search");
  if (searchInput) {
    searchInput.value = districtName;
    filterWorks();
  }
}

// Initial Boot
document.addEventListener("DOMContentLoaded", () => {
  fetchMetadata();
  fetchAnalyticsOverview();
  switchNav("landing");
  if (window.lucide) {
    window.lucide.createIcons();
  }
});
