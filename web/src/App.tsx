import { useEffect, useState } from "react"
import { motion, type Variants } from "framer-motion"
import { ShieldCheck, Activity, Box, ArrowRight, Zap, RefreshCw } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card"
import { Badge } from "./components/ui/badge"
import { Progress } from "./components/ui/progress"

interface PayloadData {
  comparison: {
    delta: number;
    disassembly: number;
    score: number;
    productId: string;
  };
  composition: Array<{
    code: string;
    pct: number;
  }>;
}

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1
    }
  }
}

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: "spring", stiffness: 300, damping: 24 }
  }
}

export default function App() {
  const [data, setData] = useState<PayloadData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(`${import.meta.env.BASE_URL}payload.json`);
        if (!response.ok) throw new Error("Failed to load payload");
        const json = await response.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  return (
    <div className="min-h-screen relative overflow-hidden flex flex-col">
      {/* Glow effects */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-blue-900/20 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-indigo-900/20 blur-[120px] rounded-full pointer-events-none" />
      
      {/* Header */}
      <header className="fixed top-0 w-full z-50 glass border-b border-white/5 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center shadow-[0_0_15px_rgba(59,130,246,0.5)]">
            <RefreshCw className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold tracking-tight text-xl">Cirquento</span>
        </div>
        <Badge variant="secondary" className="px-3 py-1">Enterprise Pipeline</Badge>
      </header>

      {/* Hero Section */}
      <main className="flex-1 pt-32 pb-16 px-6 lg:px-8 max-w-7xl mx-auto w-full z-10">
        <div className="text-center max-w-3xl mx-auto mb-20 space-y-6">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
          >
            <Badge variant="default" className="mb-4">v2.0 Active</Badge>
            <h1 className="text-5xl lg:text-7xl font-bold tracking-tight mb-6">
              The Enterprise <br />
              <span className="text-gradient-primary">Circularity Pipeline</span>
            </h1>
            <p className="text-zinc-400 text-lg lg:text-xl leading-relaxed">
              Material classification and circularity intelligence for manufacturing BOMs. Seamlessly analyze composition, assess disassembly factors, and optimize your production lifecycle.
            </p>
          </motion.div>
        </div>

        <PlaygroundPanel />
        {/* Dashboard Section */}
        {loading && (
          <div className="flex justify-center items-center h-64">
            <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          </div>
        )}

        {error && (
          <Card className="border-red-500/20 bg-red-500/5">
            <CardContent className="pt-6 flex flex-col items-center text-center text-red-400">
              <Zap className="w-12 h-12 mb-4 opacity-50" />
              <p>Failed to load circularity data.</p>
              <p className="text-sm opacity-70">{error}</p>
            </CardContent>
          </Card>
        )}

        {data && (
          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-1 lg:grid-cols-3 gap-6"
          >
            {/* Overview Column */}
            <div className="lg:col-span-1 space-y-6">
              <motion.div variants={itemVariants}>
                <Card className="h-full bg-gradient-to-br from-zinc-900/90 to-zinc-950/90 border-blue-500/20 shadow-[0_0_30px_rgba(59,130,246,0.1)] relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 blur-[50px]" />
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-zinc-200">
                      <Box className="w-5 h-5 text-blue-400" />
                      Product Analysis
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <div>
                      <p className="text-sm text-zinc-500 font-medium mb-1">Product ID</p>
                      <p className="text-2xl font-mono text-zinc-100">{data.comparison.productId}</p>
                    </div>
                    
                    <div className="space-y-2">
                      <div className="flex justify-between items-end">
                        <p className="text-sm text-zinc-500 font-medium">Circularity Score</p>
                        <p className="text-3xl font-bold text-gradient-primary">{data.comparison.score.toFixed(1)}</p>
                      </div>
                      <Progress value={data.comparison.score} className="h-2.5" />
                    </div>

                    <div className="grid grid-cols-2 gap-4 pt-4 border-t border-white/5">
                      <div>
                        <p className="text-sm text-zinc-500 font-medium mb-1 flex items-center gap-1">
                          <Activity className="w-4 h-4" /> Delta
                        </p>
                        <p className="text-xl font-semibold text-emerald-400">
                          {data.comparison.delta > 0 ? "+" : ""}{data.comparison.delta}%
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-zinc-500 font-medium mb-1 flex items-center gap-1">
                          <ShieldCheck className="w-4 h-4" /> Disassembly
                        </p>
                        <p className="text-xl font-semibold text-blue-400">
                          {data.comparison.disassembly}/100
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </div>

            {/* Composition Column */}
            <div className="lg:col-span-2">
              <motion.div variants={itemVariants} className="h-full">
                <Card className="h-full">
                  <CardHeader>
                    <CardTitle className="text-zinc-200">Material Composition</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      {data.composition.map((item, idx) => (
                        <motion.div
                          key={idx}
                          variants={itemVariants}
                          className="flex items-center gap-4 p-4 rounded-lg bg-zinc-900/50 border border-white/5 hover:bg-zinc-800/50 transition-colors"
                        >
                          <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center font-mono text-xs text-zinc-400 border border-white/5">
                            {String(idx + 1).padStart(2, '0')}
                          </div>
                          
                          <div className="flex-1">
                            <div className="flex justify-between mb-2">
                              <span className="font-medium text-zinc-200">{item.code}</span>
                              <span className="font-mono text-sm text-zinc-400">{item.pct.toFixed(2)}%</span>
                            </div>
                            <Progress value={item.pct} />
                          </div>
                          
                          <div className="ml-4 opacity-0 hover:opacity-100 transition-opacity cursor-pointer text-zinc-500 hover:text-zinc-300">
                            <ArrowRight className="w-5 h-5" />
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </div>
          </motion.div>
        )}

      {/* CTA */}
      <section className="py-32 relative overflow-hidden mt-16 border-t border-white/5">
        <motion.div
          animate={{ opacity: [0.2, 0.4, 0.2] }}
          transition={{ duration: 8, repeat: Infinity }}
          className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(59,130,246,0.15),transparent_70%)] pointer-events-none"
        />
        <div className="max-w-3xl mx-auto px-4 text-center relative z-10">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-3xl md:text-5xl font-bold tracking-tight mb-6"
          >
            Start classifying with discipline.
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.1 }}
            className="text-lg text-zinc-400 mb-10"
          >
            Clone the repo, run the tests, and see the eval gate pass.
            Zero dependencies. Zero setup. Zero excuses.
          </motion.p>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 }}
            className="flex flex-col sm:flex-row gap-4 justify-center"
          >
            <a
              href="https://github.com/DARREN-2000/cirquento"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white text-black font-semibold px-8 py-3.5 hover:bg-zinc-200 transition-all hover:-translate-y-0.5 shadow-lg"
            >
              View on GitHub
            </a>
            <div className="inline-flex items-center gap-2 rounded-lg bg-zinc-900/50 border border-white/10 px-6 py-3.5 font-[family-name:var(--font-plex-mono)] text-sm text-zinc-400">
              make verify
            </div>
          </motion.div>
        </div>
      </section>

      </main>
    </div>
  )
}


function PlaygroundPanel() {
  const [logs, setLogs] = useState<{ text: string; color: string }[]>([
    { text: "System initialized. Rules engine online.", color: "text-emerald-400" },
  ]);
  const [running, setRunning] = useState(false);

  function run() {
    if (running) return;
    setRunning(true);
    setLogs([{ text: "> Parsing BOM payload...", color: "text-emerald-400" }]);
    setTimeout(() => setLogs((l) => [...l, { text: "  [1] exact_match: False", color: "text-zinc-500" }]), 300);
    setTimeout(() => setLogs((l) => [...l, { text: "  [2] cache: miss", color: "text-zinc-500" }]), 600);
    setTimeout(() => setLogs((l) => [...l, { text: "> Escalating to Classification LLM...", color: "text-teal-400" }]), 1200);
    setTimeout(() => setLogs((l) => [...l, { text: "  [3] model_proposal: MET.ALU.WROUGHT (conf 0.95)", color: "text-zinc-300" }]), 2000);
    setTimeout(() => setLogs((l) => [...l, { text: "  ✓ classification accepted by gate", color: "text-emerald-400" }]), 2400);
    setTimeout(() => {
      setLogs((l) => [
        ...l,
        { text: "", color: "" },
        { text: "=== RESULT ======================", color: "text-teal-400" },
        { text: "code          : MET.ALU.WROUGHT", color: "text-emerald-400" },
        { text: "recyclability : 95%", color: "text-emerald-400" },
        { text: "latency       : 412ms", color: "text-zinc-400" },
        { text: "llm_used      : true", color: "text-zinc-400" },
      ]);
      setRunning(false);
    }, 3000);
  }

  return (
    <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6 bg-zinc-950/80 rounded-xl border border-white/5 mb-16 shadow-[0_0_40px_rgba(20,184,166,0.1)]">
      <div className="flex flex-col gap-3">
        <label className="font-[family-name:var(--font-plex-mono)] text-xs text-teal-400 uppercase tracking-wider">BOM Input Payload</label>
        <textarea
          className="flex-1 bg-black/60 border border-white/10 rounded-lg p-4 text-sm text-emerald-400 font-[family-name:var(--font-plex-mono)] resize-none focus:outline-none focus:border-teal-500/50 focus:ring-1 focus:ring-teal-500/20 min-h-[200px]"
          spellCheck={false}
          defaultValue={`{
  "description": "ALU EXTR 6060-T6 ANOD housing profile",
  "uom": "kg",
  "quantity": 2.5
}`}
        />
        <button
          onClick={run}
          disabled={running}
          className="w-full rounded-lg bg-gradient-to-r from-teal-500 to-cyan-600 text-white font-semibold py-3 hover:-translate-y-0.5 transition-all disabled:opacity-50 shadow-[0_4px_15px_rgba(20,184,166,0.3)]"
        >
          {running ? "Executing..." : "Execute Pipeline"}
        </button>
      </div>
      <div className="flex flex-col gap-3">
        <label className="font-[family-name:var(--font-plex-mono)] text-xs text-teal-400 uppercase tracking-wider">Execution Trace</label>
        <div className="flex-1 bg-black/60 border border-white/10 rounded-lg p-4 font-[family-name:var(--font-plex-mono)] text-sm overflow-y-auto min-h-[200px]">
          {logs.map((log, i) => (
            <div key={i} className={`${log.color} leading-relaxed`}>
              {log.text || " "}
            </div>
          ))}
          {running && <span className="text-zinc-500 animate-pulse">_</span>}
        </div>
      </div>
    </div>
  );
}
