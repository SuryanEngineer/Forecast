
  import { createRoot } from "react-dom/client";
  import App from "./app/App.tsx";
  import "./styles/index.css";
import { warmUpBackend } from "./app/lib/api";

// Wake the (free-tier) backend while the page is still loading.
warmUpBackend();

  createRoot(document.getElementById("root")!).render(<App />);
  