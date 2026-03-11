import { Sidebar } from "@/components/layout/sidebar";
import { MainArea } from "@/components/layout/main-area";

export default function App() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar />
      <MainArea />
    </div>
  );
}
