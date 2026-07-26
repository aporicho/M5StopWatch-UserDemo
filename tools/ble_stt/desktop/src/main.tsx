import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { Toaster } from "@/components/ui/toast"

import App from "./App"
import "./index.css"

const root = document.getElementById("root")

if (!root) {
  throw new Error("missing #root")
}

createRoot(root).render(
  <StrictMode>
    <Toaster>
      <App />
    </Toaster>
  </StrictMode>
)
