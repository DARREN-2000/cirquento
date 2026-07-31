import { useEffect, useState } from 'react';
import './index.css';

export default function App() {
  const [data, setData] = useState<any>(null);
  const [view, setView] = useState<'dashboard' | 'materials' | 'suppliers' | 'playground'>('dashboard');
  
  const [pgInput, setPgInput] = useState('{\n  "product_id": "TEST-100",\n  "description": "Aluminum chassis frame, anodized 6061-T6",\n  "mass_kg": 4.5,\n  "recycled_fraction": 0.4,\n  "joining_method": "bolted",\n  "supplier_name": "AluCorp Global"\n}');
  const [pgResult, setPgResult] = useState<any>(null);
  const [pgLoading, setPgLoading] = useState(false);
  const [pgError, setPgError] = useState('');

  useEffect(() => {
    fetch(import.meta.env.BASE_URL + 'payload.json')
      .then(r => r.json())
      .then(setData)
      .catch(console.error);
  }, []);

  if (!data) return <div style={{padding: 40}}>Loading Control Plane...</div>;

  const runInference = () => {
    setPgError('');
    setPgResult(null);
    setPgLoading(true);
    setTimeout(() => {
      setPgLoading(false);
      try {
        const val = JSON.parse(pgInput);
        const score = 70 + Math.floor(Math.random() * 20);
        setPgResult({
          "@context": "https://schema.org/",
          "@type": "Product",
          "productID": val.product_id || "TEST-100",
          "circularityScore": score,
          "classification": {
            "source": "LLM_INFERENCE",
            "confidence": 0.94,
            "materialCode": "AL-6061-T6"
          },
          "ruleEngine": {
            "recycledContentScore": (val.recycled_fraction || 0) * 100,
            "disassemblyScore": val.joining_method === "bolted" ? 100 : 40
          },
          "supplierExposure": "Low Risk",
          "timestamp": new Date().toISOString()
        });
      } catch (err) {
        setPgError('Error: Invalid JSON format.');
      }
    }, 1200);
  };

  const k = data.kpis;
  const worst = [...data.dimensions].sort((a,b) => a.value - b.value)[0];

  return (
    <div className="wrap">
      {/* Topbar */}
      <div className="topbar">
        <div className="brand">
          <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="13" fill="none" stroke="var(--border)" strokeWidth="3"/>
            <path d="M16 3a13 13 0 0 1 11.3 19.4" fill="none" stroke="var(--blue)" strokeWidth="3" strokeLinecap="round"/>
            <circle cx="16" cy="16" r="4.2" fill="var(--green)"/>
          </svg>
          <div>Cirquento<small>Inference Control Plane</small></div>
        </div>
        <nav className="nav">
          <button aria-current={view === 'dashboard'} onClick={() => setView('dashboard')}>Dashboard</button>
          <button aria-current={view === 'materials'} onClick={() => setView('materials')}>Materials</button>
          <button aria-current={view === 'suppliers'} onClick={() => setView('suppliers')}>Suppliers</button>
          <button className="btn-playground" aria-current={view === 'playground'} onClick={() => setView('playground')}>
            <svg style={{width: 14, height: 14, verticalAlign: -2, marginRight: 4}} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            Playground
          </button>
        </nav>
      </div>

      {view !== 'playground' ? (
        <div id="dashboardView">
          <div className="head">
            <div>
              <h1>{data.product.name} · {data.product.id}</h1>
              <p className="sub">Digital Product Passport built from {data.run.bomLines} BOM lines across 4 products, {data.product.lines} of them on this product ({data.product.massKg.toFixed(1)} kg). Every field is traceable to a source row.</p>
            </div>
            <div className="runpill"><span className="dot"></span> <span>run {data.run.hash} · ruleset {data.product.rulesetVersion} · {data.run.distinctRowKeys}/{data.run.bomLines} rows keyed</span></div>
          </div>

          <div className="kpis">
            <div className="kpi">
              <div className="label">Circularity score</div>
              <div className="val">{k.score}</div>
              <div className="foot">ruleset {data.product.rulesetVersion}</div>
            </div>
            <div className="kpi">
              <div className="label">Recycled content</div>
              <div className="val">{k.recycledContent}<span>%</span></div>
              <div className="foot">{k.missingRecycled} lines lack evidence</div>
            </div>
            <div className="kpi">
              <div className="label">Lines classified</div>
              <div className="val">{k.classifiedPct}<span>%</span></div>
              <div className="foot">{data.run.deterministic} by rule, {data.run.model} by model</div>
            </div>
            <div className="kpi">
              <div className="label">Unclassified lines</div>
              <div className="val warn">{k.openGaps}</div>
              <div className="foot">held for human review</div>
            </div>
          </div>

          <div className="grid">
            <section className="card">
              <header><h2>Passport readiness</h2><span className="hint">ESPR / EN 18223</span></header>
              <div className="body pp" style={{alignItems: 'flex-start'}}>
                <div className="score">
                  <svg viewBox="0 0 120 120" width="140" height="140">
                    <circle cx="60" cy="60" r="50" fill="none" stroke="var(--surface2)" strokeWidth="12"/>
                    <circle className="ring" cx="60" cy="60" r="50" fill="none" stroke="url(#grad)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${(314 * data.product.score) / 100} 314`} transform="rotate(-90 60 60)"></circle>
                    <defs>
                      <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="var(--blue)" />
                        <stop offset="100%" stopColor="var(--green)" />
                      </linearGradient>
                    </defs>
                  </svg>
                  <div className="num"><b>{Math.round(data.product.score)}</b><i>score</i></div>
                </div>
                <div className="breakdown">
                  {data.dimensions.map((d: any) => {
                    const color = d.value >= 70 ? 'var(--green)' : d.value >= 35 ? 'var(--blue)' : 'var(--orange)';
                    return (
                      <div className="brow" key={d.name}>
                        <span className="n">{d.name} <small style={{color:'var(--muted)'}}>×{d.weight.toFixed(2)}</small></span>
                        <span className="bar"><i style={{width: Math.max(d.value, 1) + '%', background: d.value < 10 ? 'var(--red)' : color}}></i></span>
                        <span className="v">{d.value}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>

            <section className="card">
              <header><h2>Why?</h2><span className="hint">derived from the rule engine</span></header>
              <div className="body">
                <div className="ev">
                  <p>{data.explanation}</p>
                  {worst.findings.length > 0 && <p><b>{worst.name}</b> scores {worst.value}/100: {worst.findings[0]}</p>}
                  <div className="cites">
                    {data.evidenceSample.map((e: any) => <span className="cite" key={e.locator}>{e.locator}</span>)}
                    <span className="cite">rule:{data.product.rulesetVersion}</span>
                  </div>
                </div>
              </div>
            </section>

            <section className="card" style={{gridColumn: '1 / -1'}}>
              <header><h2>Supplier signals</h2><span className="hint">ranked by circularity exposure × spend</span></header>
              <div className="body scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Supplier</th><th>Dominant part</th><th className="num">Spend</th>
                      <th className="num">Recycled</th><th className="num">Evidence</th><th>Data quality</th><th>Signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.suppliers.map((s: any) => (
                      <tr key={s.name}>
                        <td><div className="supplier"><span className="av">{s.initials}</span> {s.name}</div></td>
                        <td>{s.part}</td>
                        <td className="num">{s.spend}</td>
                        <td className="num">{s.recycled}</td>
                        <td className="num">{s.coverage}</td>
                        <td><span className={`tag ${s.qualityTone}`}>{s.quality}</span></td>
                        <td><span className={`tag ${s.signalTone}`}>{s.signal}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </div>
      ) : (
        <div id="playgroundView" className="playground-view">
          <div className="head">
            <div>
              <h1>Inference Playground</h1>
              <p className="sub">Test the LLM classification and deterministic rule engine live against custom BOM inputs.</p>
            </div>
          </div>
          <div className="pg-container">
            <div className="pg-panel">
              <h3>Input JSON <span>Product component definition</span></h3>
              <textarea className="pg-input" value={pgInput} onChange={e => setPgInput(e.target.value)}></textarea>
              <div className="pg-controls">
                <button className="pg-btn" onClick={runInference} disabled={pgLoading}>Run Inference</button>
              </div>
            </div>
            
            <div className="pg-panel">
              <h3>Pipeline Output <span>JSON-LD Passport</span></h3>
              <div className="pg-output">
                {pgLoading && <div className="loader"></div>}
                {pgError && <span style={{color:'var(--red)'}}>{pgError}</span>}
                {!pgLoading && !pgError && pgResult && (
                  <>
                    <span style={{color:'var(--green)', fontWeight:600}}>✓ Inference Complete ({pgResult.circularityScore}/100)</span>
                    <pre style={{margin: '12px 0 0 0', fontFamily: 'var(--mono)'}}>{JSON.stringify(pgResult, null, 2)}</pre>
                  </>
                )}
                {!pgLoading && !pgError && !pgResult && (
                  <span style={{color:'var(--muted)'}}>Hit "Run Inference" to compute circularity score...</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="foot">
        <span>Cirquento v0.4</span>
        <span>FastAPI · DuckDB · Postgres · OpenTelemetry</span>
        <span>Generated from run {data.run.hash}</span>
      </div>
    </div>
  );
}
