import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";

import { ApiError } from "./api/client";
import { Layout } from "./components/Layout";
import "./index.css";
import { applyTheme, settings } from "./lib/settings";
import { CheckPage } from "./pages/CheckPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewCheckPage } from "./pages/NewCheckPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      staleTime: 5_000,
    },
  },
});

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <NewCheckPage /> },
      { path: "/history", element: <HistoryPage /> },
      { path: "/checks/:id", element: <CheckPage /> },
    ],
  },
]);

window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => settings.getTheme() === "system" && applyTheme("system"));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
