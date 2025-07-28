import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from "@/components/ui/form"
import './App.css'

import { useState, useEffect } from "react";
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import * as z from "zod"

// Form schema
const formSchema = z.object({
  mwp: z.string().min(1, "Please enter a math word problem"),
  formula: z.string().optional(),
})

const resubmitSchema = z.object({
  dsl: z.string().min(1, "Visual language cannot be empty"),
})

type FormData = z.infer<typeof formSchema>
type ResubmitData = z.infer<typeof resubmitSchema>

// Type definitions
interface ApiResponse {
  visual_language: string;
  svg_formal: string;
  svg_intuitive: string;
  error?: string;
}

interface ApiRequest {
  mwp?: string;
  formula?: string;
  dsl?: string;
}

function App() {
  const [vl, setVl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [svgFormal, setSvgFormal] = useState<string | null>(null);
  const [svgIntuitive, setSvgIntuitive] = useState<string | null>(null);

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      mwp: "",
      formula: "",
    },
  })

  const resubmitForm = useForm<ResubmitData>({
    resolver: zodResolver(resubmitSchema),
    defaultValues: {
      dsl: "",
    },
  })

  const handleResubmit = async (data: ResubmitData) => {
    setError(null);
    setLoading(true);
    setSvgFormal(null);
    setSvgIntuitive(null);

    try {
      const res = await fetch("http://localhost:5001/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dsl: data.dsl } as ApiRequest)
      });
      const result: ApiResponse = await res.json();
      if (!res.ok) throw new Error(result.error || "Unknown error");
      setVl(result.visual_language);
      setSvgFormal(result.svg_formal);
      setSvgIntuitive(result.svg_intuitive);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "An unknown error occurred";
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (data: FormData) => {
    setError(null);
    setLoading(true);
    setVl(null);
    setSvgFormal(null);
    setSvgIntuitive(null);

    try {
      const res = await fetch("http://localhost:5001/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mwp: data.mwp, formula: data.formula } as ApiRequest)
      });
      const result: ApiResponse = await res.json();
      if (!res.ok) throw new Error(result.error || "Unknown error");
      setVl(result.visual_language);
      setSvgFormal(result.svg_formal);
      setSvgIntuitive(result.svg_intuitive);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "An unknown error occurred";
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (vl !== null) {
      resubmitForm.setValue("dsl", vl);
    }
  }, [vl, resubmitForm]);

  const downloadSvg = (svgContent: string, filename: string) => {
    const blob = new Blob([svgContent], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen w-full p-8 max-w-6xl mx-auto">
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold mb-4">Math2Visual</h1>
        <p className="text-muted-foreground">Enter your math word problem to generate visual representations</p>
      </div>

      <div className="max-w-2xl mx-auto">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="mwp"
              render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <Textarea
                      className="w-full"
                      placeholder="Enter your math word problem…"
                      rows={4}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="formula"
              render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <Input
                      className="w-full"
                      placeholder="Optional formula (e.g. 9 + 7 = 16)"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="flex justify-center mt-6">
              <Button
                type="submit"
                disabled={loading}
                size="lg"
                className="min-w-[200px] bg-primary text-primary-foreground"
              >
                {loading ? "Generating…" : "Generate Visualization"}
              </Button>
            </div>
          </form>
        </Form>

        {error && (
          <div className="mt-6 p-4 bg-destructive/10 border border-destructive/20 rounded-md">
            <p className="text-destructive font-medium">Error: {error}</p>
          </div>
        )}

        {vl && (
          <div className="mt-8 space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-4">Visual Language</h2>
              
              <Form {...resubmitForm}>
                <form onSubmit={resubmitForm.handleSubmit(handleResubmit)} className="space-y-4">
                  <FormField
                    control={resubmitForm.control}
                    name="dsl"
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <Textarea
                            className="w-full font-mono text-sm"
                            rows={6}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <div className="flex justify-center">
                    <Button
                      type="submit"
                      disabled={loading}
                      variant="secondary"
                      className="min-w-[200px]"
                    >
                      {loading ? (
                        <>
                          <div className="loading-spinner mr-2"></div>
                          Updating…
                        </>
                      ) : (
                        "Resubmit Visualization"
                      )}
                    </Button>
                  </div>
                </form>
              </Form>
            </div>
          </div>
        )}
      </div>

      {svgFormal && svgIntuitive && (
        <div className="mt-12">
          <h2 className="text-2xl font-semibold mb-6 text-center">Generated Visualizations</h2>
          
          <div className="svg-row">
            <div className="space-y-4">
              <div 
                className="svg-box"
                onClick={() => downloadSvg(svgFormal, 'formal-visualization.svg')}
                title="Click to download"
              >
                <div dangerouslySetInnerHTML={{ __html: svgFormal }} />
              </div>
              <p className="text-center font-medium text-muted-foreground">Formal Representation</p>
            </div>
            
            <div className="space-y-4">
              <div 
                className="svg-box"
                onClick={() => downloadSvg(svgIntuitive, 'intuitive-visualization.svg')}
                title="Click to download"
              >
                <div dangerouslySetInnerHTML={{ __html: svgIntuitive }} />
              </div>
              <p className="text-center font-medium text-muted-foreground">Intuitive Representation</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;