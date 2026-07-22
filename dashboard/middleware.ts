import { NextRequest, NextResponse } from "next/server";

// Gates the whole dashboard behind HTTP Basic Auth. Runs everywhere the
// dashboard runs (local `next dev`, Hostinger open deploy, behind Traefik)
// so there's one secret to manage instead of Traefik basicauth + this.
// Unset DASHBOARD_USER/PASSWORD = open, matching the existing "blank
// API_KEY = open" convention in app/core/auth.py (local dev only).
export function middleware(request: NextRequest) {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  if (!user || !password) return NextResponse.next();

  const auth = request.headers.get("authorization");
  if (auth) {
    const [scheme, encoded] = auth.split(" ");
    if (scheme === "Basic" && encoded) {
      const [u, p] = Buffer.from(encoded, "base64").toString().split(":");
      if (u === user && p === password) return NextResponse.next();
    }
  }

  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="ai-company dashboard"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
