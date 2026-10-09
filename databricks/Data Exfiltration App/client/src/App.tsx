import { createBrowserRouter, RouterProvider, NavLink, Outlet } from 'react-router';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
  Label,
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Separator,
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
  useAnalyticsQuery,
  useIsMobile,
} from '@databricks/appkit-ui/react';
import {
  Activity,
  AlertTriangle,
  Ban,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Columns3,
  Copy,
  Database,
  FileCode,
  FileDown,
  Filter,
  Fingerprint,
  FolderOpen,
  Inbox,
  Info,
  KeyRound,
  Lock,
  Menu,
  Network,
  RefreshCw,
  Search,
  Server,
  Share2,
  ShieldAlert,
  ShieldCheck,
  User,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

const PAGE_SIZE = 5;

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? 'bg-primary-foreground text-primary shadow-sm'
      : 'text-primary-foreground/80 hover:bg-primary-foreground/10 hover:text-primary-foreground'
  }`;

const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? 'bg-primary text-primary-foreground'
      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

type NavLinkClassFn = (props: { isActive: boolean }) => string;

type RequestRow = {
  id: string;
  submitter: string;
  dataset: string;
  justification: string;
  format: string;
  status: string;
  created_at?: string;
  steward?: string;
  steward_comment?: string;
  output_url?: string;
  output_table?: string;
  expires_at?: string;
  consent_group?: string;
  // Cohort definition (Query-ID analog), stored as JSON strings on the request.
  selected_columns?: string;
  cohort_filter?: string;
};

// Structured cohort filter shared by the Submit form, the steward modal, and
// the My Requests summary — never a raw SQL string.
type CohortFilterDef = { column: string; op: string; value: string };

const COHORT_OP_LABELS: Record<string, string> = {
  eq: '=',
  ne: '\u2260',
  lt: '<',
  lte: '\u2264',
  gt: '>',
  gte: '\u2265',
  contains: 'contains',
};

function parseCohortColumns(v?: string | null): string[] {
  if (!v) return [];
  try {
    const a = JSON.parse(v);
    return Array.isArray(a) ? a.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function parseCohortFilter(v?: string | null): CohortFilterDef | null {
  if (!v) return null;
  try {
    const o = JSON.parse(v);
    if (o && typeof o.column === 'string' && typeof o.op === 'string') {
      return { column: o.column, op: o.op, value: String(o.value ?? '') };
    }
  } catch {
    /* ignore malformed */
  }
  return null;
}

function describeCohortFilter(f: CohortFilterDef): string {
  const op = COHORT_OP_LABELS[f.op] ?? f.op;
  return f.op === 'contains' ? `${f.column} ${op} "${f.value}"` : `${f.column} ${op} ${f.value}`;
}

// Rows key on `request_id` (the Delta column name), whether they come from the
// analytics SSE result or the uncached live endpoints; the rest of the app
// keeps using `id` for routing/keys.
function toRequestRow(row: { request_id: string } & Record<string, unknown>): RequestRow {
  const { request_id, ...rest } = row;
  return { id: request_id, ...(rest as Omit<RequestRow, 'id'>) };
}

// The steward_queue view enriches each pending request with study context and
// the submitter's live DAR/access decision, surfaced in the details modal.
type StewardRequestRow = RequestRow & {
  study_name?: string;
  access_tier?: string;
  dbgap_status?: string;
  consent_group?: string;
  submitter_role?: string;
  submitter_expiration_ts?: number;
  submitter_decision?: string;
  submitter_decision_basis?: string;
};

function toStewardRow(row: { request_id: string } & Record<string, unknown>): StewardRequestRow {
  const { request_id, ...rest } = row;
  return { id: request_id, ...(rest as Omit<StewardRequestRow, 'id'>) };
}

/**
 * Fetch a JSON array from an uncached app endpoint, with an initial load plus
 * optional visibility-aware polling and a manual `refresh()`. Used for the
 * request-tracking views (steward queue / my requests) that must reflect
 * writes immediately — the analytics SSE path caches results for an hour and
 * never refetches, so those surfaces would otherwise show stale data.
 */
function useLiveResource<T>(url: string, opts?: { intervalMs?: number }) {
  const intervalMs = opts?.intervalMs ?? 0;
  const [data, setData] = useState<T[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const initialisedRef = useRef(false);

  const fetchNow = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    if (initialisedRef.current) setRefreshing(true);
    setError(null);
    try {
      const resp = await fetch(url, { signal: ac.signal, headers: { 'cache-control': 'no-cache' } });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.error ? String(body.error) : `Request failed (${resp.status}).`);
      }
      setData((await resp.json()) as T[]);
    } catch (e) {
      if ((e as { name?: string }).name === 'AbortError') return;
      setError(e instanceof Error ? e.message : 'Unable to load data.');
    } finally {
      setLoading(false);
      setRefreshing(false);
      initialisedRef.current = true;
    }
  }, [url]);

  useEffect(() => {
    setLoading(true);
    initialisedRef.current = false;
    fetchNow();
    return () => abortRef.current?.abort();
  }, [fetchNow]);

  useEffect(() => {
    if (!intervalMs) return;
    const tick = () => {
      if (document.visibilityState === 'visible') fetchNow();
    };
    const timer = setInterval(tick, intervalMs);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [fetchNow, intervalMs]);

  return { data, loading, error, refresh: fetchNow, refreshing };
}

type AuditRow = {
  event_id: string;
  timestamp: string;
  user: string;
  action_type: string;
  resource: string;
  outcome: string;
  // Databricks analytics returns JSON-string columns as parsed objects at runtime
  details?: string | Record<string, unknown>;
};

type Tone = 'default' | 'primary' | 'success' | 'warning' | 'destructive';

const STATUS_META: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  pending: { label: 'Pending', icon: Clock3, className: 'border-warning/30 bg-warning/10 text-warning' },
  approved: { label: 'Approved', icon: CheckCircle2, className: 'border-success/30 bg-success/10 text-success' },
  rejected: { label: 'Rejected', icon: XCircle, className: 'border-destructive/30 bg-destructive/10 text-destructive' },
  submitted: { label: 'Submitted', icon: FileDown, className: 'border-primary/30 bg-primary/10 text-primary' },
  granted: { label: 'Granted', icon: CheckCircle2, className: 'border-success/30 bg-success/10 text-success' },
  denied: { label: 'Denied', icon: XCircle, className: 'border-destructive/30 bg-destructive/10 text-destructive' },
  flagged_for_review: { label: 'Flagged', icon: ShieldAlert, className: 'border-warning/30 bg-warning/10 text-warning' },
  blocked: { label: 'Blocked', icon: Ban, className: 'border-destructive/30 bg-destructive/10 text-destructive' },
  allowed: { label: 'Allowed', icon: CheckCircle2, className: 'border-success/30 bg-success/10 text-success' },
};

function statusMeta(status: string) {
  return (
    STATUS_META[status] ?? {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      icon: Activity,
      className: 'border-border bg-muted text-muted-foreground',
    }
  );
}

function StatusBadge({ status }: { status: string }) {
  const meta = statusMeta(status);
  const Icon = meta.icon;
  return (
    <Badge variant="outline" className={`gap-1 font-medium ${meta.className}`}>
      <Icon className="h-3.5 w-3.5" />
      {meta.label}
    </Badge>
  );
}

function FormatBadge({ format }: { format: string }) {
  return (
    <Badge variant="secondary" className="text-[10px] font-semibold uppercase tracking-wide">
      {format}
    </Badge>
  );
}

function detailsToString(details: string | Record<string, unknown> | undefined | null): string {
  if (details === null || details === undefined) return '';
  if (typeof details === 'string') return details;
  return JSON.stringify(details);
}

function formatDate(iso?: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function toneClasses(tone: Tone = 'default') {
  switch (tone) {
    case 'primary':
      return 'bg-primary/10 text-primary';
    case 'success':
      return 'bg-success/15 text-success';
    case 'warning':
      return 'bg-warning/15 text-warning';
    case 'destructive':
      return 'bg-destructive/15 text-destructive';
    default:
      return 'bg-muted text-muted-foreground';
  }
}

function StatBand({ stats }: { stats: { label: string; value: number; icon: LucideIcon; tone?: Tone }[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((s) => (
        <Card key={s.label} className="border-none bg-muted/40 shadow-sm">
          <CardContent className="flex items-center gap-3 p-4">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${toneClasses(s.tone)}`}>
              <s.icon className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-2xl font-semibold leading-none text-foreground">{s.value}</div>
              <div className="mt-1 truncate text-xs text-muted-foreground">{s.label}</div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function StatBandSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-[68px] rounded-lg" />
      ))}
    </div>
  );
}

function getPageRange(page: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | 'ellipsis')[] = [1];
  if (page > 3) pages.push('ellipsis');
  for (let p = Math.max(2, page - 1); p <= Math.min(total - 1, page + 1); p++) pages.push(p);
  if (page < total - 2) pages.push('ellipsis');
  pages.push(total);
  return pages;
}

function PageNav({ page, totalPages, onPageChange }: { page: number; totalPages: number; onPageChange: (page: number) => void }) {
  if (totalPages <= 1) return null;
  const pages = getPageRange(page, totalPages);
  return (
    <Pagination>
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            href="#"
            onClick={(e) => {
              e.preventDefault();
              if (page > 1) onPageChange(page - 1);
            }}
            className={page === 1 ? 'pointer-events-none opacity-50' : ''}
          />
        </PaginationItem>
        {pages.map((p, i) =>
          p === 'ellipsis' ? (
            <PaginationItem key={`ellipsis-${i}`}>
              <PaginationEllipsis />
            </PaginationItem>
          ) : (
            <PaginationItem key={p}>
              <PaginationLink
                href="#"
                isActive={p === page}
                onClick={(e) => {
                  e.preventDefault();
                  onPageChange(p);
                }}
              >
                {p}
              </PaginationLink>
            </PaginationItem>
          ),
        )}
        <PaginationItem>
          <PaginationNext
            href="#"
            onClick={(e) => {
              e.preventDefault();
              if (page < totalPages) onPageChange(page + 1);
            }}
            className={page === totalPages ? 'pointer-events-none opacity-50' : ''}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}

function SearchFilterBar({
  search,
  onSearchChange,
  placeholder,
  children,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  placeholder: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={search} onChange={(e) => onSearchChange(e.target.value)} placeholder={placeholder} className="pl-9" />
      </div>
      {children}
    </div>
  );
}

// Shared identity context. Identity is READ-ONLY on the client:
// - `user` comes from GET /api/me (x-forwarded-email set by the Databricks Apps proxy)
// - `isSteward` comes from an OBO query evaluating is_account_group_member('bdc-stewards')
//   with the caller's own Unity Catalog identity. There is no client-side role state;
// changing the role means changing UC group membership.
type IdentityState = {
  user: string | null;
  isSteward: boolean;
  loading: boolean;
  error: string | null;
  retry: () => void;
};

const IdentityContext = createContext<IdentityState>({
  user: null,
  isSteward: false,
  loading: true,
  error: null,
  retry: () => {},
});

type RoleProbeState = {
  // The analytics runtime returns SQL BOOLEAN cells as the raw string
  // "true"/"false" (only STRING columns are JSON-parsed), so the value can be
  // either a real boolean or its string form — normalize at the read site.
  data: { user_email: string; is_steward: boolean | string; is_analyst: boolean | string }[] | null;
  loading: boolean;
  error: string | null;
};

// Runs the OBO is_steward query and reports its state upward. This is a
// separate component (rather than a hook in the provider) so it can be
// remounted via `key` to force a fresh query — useAnalyticsQuery exposes no
// refetch of its own.
function RoleProbe({ onState }: { onState: (s: RoleProbeState) => void }) {
  const { data, loading, error } = useAnalyticsQuery('is_steward', {});
  useEffect(() => {
    onState({ data: data ?? null, loading, error });
  }, [data, loading, error, onState]);
  return null;
}

// The OBO role query can fail transiently — most commonly while the serverless
// SQL warehouse cold-starts (it auto-stops when idle), which surfaces as an
// aborted/UPSTREAM_ERROR. Auto-retry a few times with backoff before giving up
// so a cold start doesn't strand the user on "Role unavailable".
const MAX_AUTO_RETRIES = 4;

function IdentityProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<string | null>(null);
  const [meError, setMeError] = useState<string | null>(null);
  const [probeKey, setProbeKey] = useState(0);
  const [autoRetries, setAutoRetries] = useState(0);
  const [role, setRole] = useState<RoleProbeState>({ data: null, loading: true, error: null });

  const onState = useCallback((s: RoleProbeState) => setRole(s), []);

  // (Re)fetch the display identity whenever we (re)issue the role probe.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/me')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((body: { user: string }) => {
        if (!cancelled) setUser(body.user);
      })
      .catch((e: Error) => {
        if (!cancelled) setMeError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [probeKey]);

  const reissue = useCallback(() => {
    setRole({ data: null, loading: true, error: null });
    setMeError(null);
    setProbeKey((k) => k + 1);
  }, []);

  // Manual retry: reset the auto-retry budget and issue a fresh probe.
  const retry = useCallback(() => {
    setAutoRetries(0);
    reissue();
  }, [reissue]);

  // Reset the auto-retry budget once the role resolves.
  useEffect(() => {
    if (role.data) setAutoRetries(0);
  }, [role.data]);

  // Auto-retry transient role failures with exponential backoff.
  useEffect(() => {
    if (!role.error || autoRetries >= MAX_AUTO_RETRIES) return;
    const delay = Math.min(1000 * 2 ** autoRetries, 8000);
    const timer = setTimeout(() => {
      setAutoRetries((n) => n + 1);
      reissue();
    }, delay);
    return () => clearTimeout(timer);
  }, [role.error, autoRetries, reissue]);

  const row = role.data?.[0];
  const exhausted = autoRetries >= MAX_AUTO_RETRIES;

  let loading: boolean;
  let error: string | null;
  if (row) {
    loading = false;
    error = null;
  } else if (role.error) {
    // Keep the UI in a loading state while we still have retries to burn, so a
    // cold-start blip shows a spinner rather than a scary "Role unavailable".
    loading = !exhausted;
    error = exhausted ? (role.error ?? meError) : null;
  } else {
    loading = true;
    error = null;
  }

  const value: IdentityState = {
    user: row?.user_email ?? user,
    isSteward: row?.is_steward === true || row?.is_steward === 'true',
    loading,
    error,
    retry,
  };

  return (
    <IdentityContext.Provider value={value}>
      <RoleProbe key={probeKey} onState={onState} />
      {children}
    </IdentityContext.Provider>
  );
}

const STEWARD_ONLY_PATHS = new Set(['/steward-queue', '/audit']);

function NavLinks({ className, linkClass, onClick }: { className?: string; linkClass: NavLinkClassFn; onClick?: () => void }) {
  const { isSteward } = useContext(IdentityContext);
  return (
    <nav className={className}>
      <NavLink to="/" end className={linkClass} onClick={onClick}>
        Home
      </NavLink>
      <NavLink to="/submit" className={linkClass} onClick={onClick}>
        Submit Request
      </NavLink>
      <NavLink to="/my-requests" className={linkClass} onClick={onClick}>
        My Requests
      </NavLink>
      {isSteward && (
        <NavLink to="/steward-queue" className={linkClass} onClick={onClick}>
          Steward Queue
        </NavLink>
      )}
      {isSteward && (
        <NavLink to="/audit" className={linkClass} onClick={onClick}>
          Audit
        </NavLink>
      )}
      <NavLink to="/about" className={linkClass} onClick={onClick}>
        About
      </NavLink>
    </nav>
  );
}

function IdentityBadge() {
  const { user, isSteward, loading, error, retry } = useContext(IdentityContext);
  if (loading) return <Skeleton className="h-7 w-40 rounded-full" />;
  const shortName = user && user.includes('@') ? user.split('@')[0] : (user ?? 'unknown');
  const initial = shortName.trim().charAt(0).toUpperCase() || '?';
  // When the role query fails we cannot distinguish Analyst from Steward, so
  // never silently fall back to "Analyst" — surface the failure instead.
  const roleUnavailable = error != null;
  return (
    <div className="flex items-center gap-2 rounded-full border border-primary-foreground/20 bg-primary-foreground/10 py-1 pl-1 pr-3">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-foreground text-xs font-semibold text-primary">
        {initial}
      </div>
      <span className="max-w-40 truncate text-xs text-primary-foreground" title={user ?? undefined}>
        {user ?? 'unknown'}
      </span>
      {roleUnavailable ? (
        <button
          type="button"
          onClick={retry}
          className="flex items-center gap-1 rounded-full border border-amber-300/70 bg-amber-400/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-amber-100 transition-colors hover:bg-amber-400/30"
          title={`Could not verify Unity Catalog group membership: ${error}. Click to retry, or sign out and back in to re-authorize the app.`}
        >
          <AlertTriangle className="h-3 w-3" />
          Role unavailable
          <RefreshCw className="h-3 w-3" />
        </button>
      ) : (
        <Badge
          variant="outline"
          className={`text-[10px] uppercase tracking-wide ${
            isSteward
              ? 'border-primary-foreground/60 bg-primary-foreground text-primary'
              : 'border-primary-foreground/40 text-primary-foreground/90'
          }`}
          title="Resolved from Unity Catalog group membership (bdc-stewards); not editable in the app"
        >
          {isSteward ? 'Steward' : 'Analyst'}
        </Badge>
      )}
    </div>
  );
}

function Layout() {
  const isMobile = useIsMobile();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (!isMobile) setMobileNavOpen(false);
  }, [isMobile]);

  return (
    <IdentityProvider>
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b border-primary-foreground/10 bg-primary px-4 text-primary-foreground shadow-sm md:px-6 py-3 flex items-center gap-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 shrink-0" />
          <div className="leading-tight">
            <div className="text-lg font-semibold">Axle Data Export Portal</div>
            <div className="hidden text-[11px] font-normal text-primary-foreground/70 lg:block">
              Consent-aware controls for governed analysis, export review, and audit evidence
            </div>
          </div>
        </div>
        <NavLinks className="hidden md:flex gap-1" linkClass={navLinkClass} />
        <div className="ml-auto hidden md:flex items-center gap-2">
          <IdentityBadge />
        </div>
        <div className="ml-auto md:hidden">
          <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <Button
              variant="ghost"
              size="icon"
              className="text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground"
              onClick={() => setMobileNavOpen(true)}
            >
              <Menu className="h-5 w-5" />
              <span className="sr-only">Open navigation</span>
            </Button>
            <SheetContent side="left">
              <SheetHeader>
                <SheetTitle>Navigation</SheetTitle>
              </SheetHeader>
              <NavLinks className="flex flex-col gap-1" linkClass={mobileNavLinkClass} onClick={() => setMobileNavOpen(false)} />
              <Separator className="my-3" />
              <div className="px-3">
                <IdentityBadge />
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </header>

      <main className="flex-1 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
    </IdentityProvider>
  );
}

/**
 * Route-level enforcement for steward pages. The underlying data is ALSO
 * row-filtered in Unity Catalog (steward_queue returns zero rows for
 * non-stewards), so this guard is presentation, not the security boundary.
 */
function RequireSteward({ children }: { children: ReactNode }) {
  const { isSteward, loading, error, retry } = useContext(IdentityContext);
  if (loading) {
    return (
      <div className="mx-auto max-w-4xl space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 rounded-lg" />
      </div>
    );
  }
  // If we could not resolve the role at all, don't assert a definitive 403 —
  // the user may in fact be a steward whose session lost the required scope.
  if (error != null) {
    return (
      <div className="mx-auto max-w-4xl">
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Could not verify your role</AlertTitle>
          <AlertDescription>
            We couldn't confirm your Unity Catalog group membership, so this steward-only page is hidden. This is often a
            transient warehouse cold-start — retry below. If it persists, sign out and sign back in to re-authorize the app.
            <span className="mt-1 block text-xs opacity-70">{error}</span>
            <Button variant="outline" size="sm" className="mt-3" onClick={retry}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }
  if (!isSteward) {
    return (
      <div className="mx-auto max-w-4xl">
        <Alert variant="destructive">
          <Lock className="h-4 w-4" />
          <AlertTitle>403 — Stewards only</AlertTitle>
          <AlertDescription>
            This page requires membership in the <code>bdc-stewards</code> Unity Catalog group. Your account is not a
            member. Access is controlled by group membership, not by anything in this app.
          </AlertDescription>
        </Alert>
      </div>
    );
  }
  return <>{children}</>;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/submit', element: <SubmitRequestPage /> },
      { path: '/my-requests', element: <MyRequestsPage /> },
      { path: '/steward-queue', element: <RequireSteward><StewardQueuePage /></RequireSteward> },
      { path: '/audit', element: <RequireSteward><AuditPage /></RequireSteward> },
      { path: '/about', element: <AboutPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}

/**
 * Four real Unity Catalog mechanisms for making this same governed data
 * available elsewhere — none of which produce a raw file export. Copy here is
 * purely educational; selecting one only swaps in the explanation text.
 */
const EXPORT_PATH_OPTIONS = [
  {
    id: 'delta_sharing',
    label: 'D2D Delta Sharing',
    icon: Share2,
    description:
      'Creates a live, read-only share between Unity Catalog metastores. No file is copied \u2014 the recipient queries the same governed data in place, and every access is checked and logged just like this app does.',
  },
  {
    id: 'lakehouse_federation',
    label: 'Lakehouse Federation',
    icon: Network,
    description:
      'Connect an external analysis platform so its data can be queried directly through Unity Catalog without copying or ingesting it. The same row- and column-level permissions configured here still apply.',
  },
  {
    id: 'iceberg_rest',
    label: 'Iceberg / UC REST API',
    icon: KeyRound,
    description:
      'Other compute engines authenticate through Unity Catalog and get short-lived, credential-vended access to read the data directly \u2014 never a static file handed off.',
  },
  {
    id: 'volumes',
    label: 'Volumes',
    icon: FolderOpen,
    description:
      'For non-tabular files like VCFs or notebooks, Volumes give the same governed, audited read access as tables do, without opening a general-purpose export path.',
  },
] as const;

const FEDRAMP_BOUNDARY_NOTE =
  'All four paths stay inside the same FedRAMP authorization boundary \u2014 none produce a raw file export.';

/**
 * Replaces the (removed) real download button. Purely educational: explains
 * how Unity Catalog can move this same governed data via four real mechanisms,
 * all inside the platform's existing FedRAMP boundary. No file transfer happens
 * here — selecting an option swaps in explainer copy.
 */
function ExportPathSelector({ req }: { req: RequestRow }) {
  // Notebooks are non-tabular, so Volumes is the only sensible export path.
  const notebook = isNotebookFormat(req.format);
  const options = notebook ? EXPORT_PATH_OPTIONS.filter((o) => o.id === 'volumes') : EXPORT_PATH_OPTIONS;
  const [selected, setSelected] = useState<string | undefined>(notebook ? 'volumes' : undefined);
  const selectedOption = EXPORT_PATH_OPTIONS.find((o) => o.id === selected);
  const triggerId = `export-path-${req.id}`;

  return (
    <div className="w-full space-y-1.5 sm:w-72">
      <Label htmlFor={triggerId} className="text-xs text-muted-foreground">
        Export via{notebook ? ' (notebook — Volumes only)' : ''}
      </Label>
      <Select value={selected} onValueChange={setSelected}>
        <SelectTrigger id={triggerId} className="w-full">
          <SelectValue placeholder="Select export method" />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => {
            const Icon = opt.icon;
            return (
              <SelectItem key={opt.id} value={opt.id}>
                <Icon className="mr-1.5 h-3.5 w-3.5" />
                {opt.label}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>

      <div aria-live="polite">
        {selectedOption ? (
          <div
            key={selectedOption.id}
            className="animate-in fade-in-0 slide-in-from-top-1 space-y-1.5 rounded-md border bg-muted/30 p-2.5 text-xs duration-200"
          >
            <div className="flex flex-wrap items-center gap-1.5 font-medium text-foreground">
              <selectedOption.icon className="h-3.5 w-3.5 text-primary" />
              {selectedOption.label}
            </div>
            <p className="text-muted-foreground">{selectedOption.description}</p>
            <div className="flex items-start gap-1.5 border-t pt-1.5 text-[11px] text-muted-foreground">
              <Lock className="mt-0.5 h-3 w-3 shrink-0" />
              {FEDRAMP_BOUNDARY_NOTE}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const EXPLORE_LINKS: { to: string; label: string; description: string; icon: LucideIcon }[] = [
  { to: '/submit', label: 'Submit Request', description: 'Request an export; a current_user()-scoped UC view decides access before you can send it.', icon: FileDown },
  { to: '/my-requests', label: 'My Requests', description: 'Track your requests; exports are scoped to your identity, labeled by egress path, and expire.', icon: ClipboardList },
  { to: '/steward-queue', label: 'Steward Queue', description: 'Act on requests a UC row-filtered view exposes only to bdc-stewards.', icon: ShieldCheck },
  { to: '/audit', label: 'Audit Log', description: 'App events plus Unity Catalog\u2019s own system.access.audit platform trail.', icon: Activity },
  { to: '/about', label: 'About', description: 'How this demo was built in Cursor and the Databricks UC + settings needed to run it.', icon: Info },
];

/**
 * Honest, stated scope limit — this is a boundary of the design, not a bug.
 * Shown under the Activity Log.
 */
function ScopeLimitNote() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-muted-foreground/20 bg-muted/40 p-4 text-sm">
      <Network className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="font-medium text-foreground">Scope of this layer</div>
        <p className="mt-0.5 text-muted-foreground">
          This layer governs what can be exposed via direct download, volume copy (to a connected external cloud account),
          or SBFS mount. It cannot reach data once it has already left the platform through one of these paths. That is a
          stated boundary of where platform-side governance applies &mdash; not a defect.
        </p>
      </div>
    </div>
  );
}

function AboutPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-primary">
          <Info className="h-4 w-4" />
          About this demo
        </div>
        <h2 className="text-2xl font-semibold text-foreground">Axle Data Export Portal</h2>
        <p className="text-sm text-muted-foreground">
          A proof-of-concept built at Axle in Cursor, showing how Databricks and Unity Catalog can govern
          controlled-access research data end to end &mdash; deciding access on the requester&rsquo;s real identity, routing
          exports through a steward review, and recording every action in a dual audit trail. This page documents what the
          demo shows, how it was built, and the Databricks configuration required to run it.
        </p>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            What this demonstrates
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li>
              <span className="font-medium text-foreground">Forwarded-identity auth.</span> The app trusts the platform&rsquo;s
              authenticated user &mdash; there is no client-supplied role state to tamper with.
            </li>
            <li>
              <span className="font-medium text-foreground">Self-enforcing access.</span> A{' '}
              <code>current_user()</code>-scoped Unity Catalog view (<code>export_decision</code>) decides each
              dataset&rsquo;s outcome; the UI cannot override it.
            </li>
            <li>
              <span className="font-medium text-foreground">Roles by group membership.</span> Analyst vs. steward is
              determined by Unity Catalog account-group membership (<code>is_account_group_member()</code>), re-checked
              server-side on every privileged action.
            </li>
            <li>
              <span className="font-medium text-foreground">On-behalf-of (OBO) reads.</span> Permission-sensitive queries
              run as the end user, so UC grants, row filters, and column masks apply to them directly.
            </li>
            <li>
              <span className="font-medium text-foreground">Steward-reviewed exports.</span> Approval mints a governed,
              expiring Delta artifact; raw tables are never granted to users &mdash; the app is the only path to the bytes.
            </li>
            <li>
              <span className="font-medium text-foreground">Dual audit trail.</span> The app&rsquo;s own{' '}
              <code>audit_events</code> table plus Unity Catalog&rsquo;s platform <code>system.access.audit</code> log.
            </li>
          </ul>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-primary" />
            How it was built in Cursor
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            The base project was generated with the Databricks <span className="font-medium text-foreground">AppKit</span>{' '}
            scaffolder &mdash; a React 19 + Vite + Tailwind + shadcn/Radix front end, an Express server, and
            analytics-plugin SQL under <code>config/queries/</code>. The stack is <code>@databricks/appkit</code> +{' '}
            <code>@databricks/appkit-ui</code>, <code>@databricks/sdk-experimental</code>, react-router 7, zod, lucide, and
            Tailwind 4.
          </p>
          <div>
            <div className="font-medium text-foreground">How it evolved</div>
            <ul className="mt-1 space-y-1.5">
              <li>Started from a spec that used a simulated persona toggle; rebuilt on real Unity Catalog enforcement instead.</li>
              <li>Removed client-side role simulation; identity now comes from forwarded proxy headers and UC account groups.</li>
              <li>Hardened identity resolution with retry/backoff so a cold-warehouse OBO failure no longer mislabels a steward.</li>
              <li>Added a governed data-file preview over UC volumes (paging + row counts), gated on the export decision.</li>
              <li>Export hardening: approval mints a per-request governed Delta table with lineage and provenance tags; downloads are app-mediated, expiring, and re-validated.</li>
              <li>Fixed a data-freshness issue (a 1-hour analytics cache) with uncached OBO live endpoints and a <code>useLiveResource</code> polling/refresh hook.</li>
              <li>Replaced the raw download control with an educational export-path explainer (Delta Sharing, Lakehouse Federation, Iceberg / UC REST, Volumes).</li>
            </ul>
          </div>
          <div>
            <div className="font-medium text-foreground">The build loop</div>
            <ol className="mt-1 list-decimal space-y-1 pl-5">
              <li>Edit <code>server/server.ts</code>, <code>client/src/App.tsx</code>, and/or <code>sql/*.sql</code> in Cursor.</li>
              <li><code>npm run build</code> (server: <code>tsc</code> + <code>tsdown</code>; client: <code>tsc</code> + <code>vite</code>).</li>
              <li>Apply SQL changes via the Databricks Statement Execution API on the SQL warehouse.</li>
              <li><code>databricks bundle deploy -p artdscs</code>, then <code>databricks bundle run app</code>.</li>
              <li>Verify in the running app; keep <code>docs/SPEC.md</code> in sync as the authoritative spec.</li>
            </ol>
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4 text-primary" />
            Databricks configuration to run this app
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <div>
            <div className="flex items-center gap-1.5 font-medium text-foreground">
              <Database className="h-3.5 w-3.5 text-primary" /> Unity Catalog
            </div>
            <ul className="mt-1 space-y-1.5">
              <li>A governed catalog with a default schema holding <code>export_requests</code>, <code>audit_events</code>, <code>study_catalog</code>, and a per-user permissions table.</li>
              <li>Self-scoped views: <code>export_decision</code> (resolved with <code>current_user()</code>), plus steward-only, row-filtered <code>steward_queue</code> and <code>audit_events_scoped</code> views.</li>
              <li>A separate <code>export_outputs</code> schema for the per-request governed Delta artifacts minted at approval.</li>
              <li>Two account-level groups &mdash; an analyst group and a steward group &mdash; with grants issued to the <span className="font-medium text-foreground">groups, never individuals</span>: <code>USE CATALOG</code>/<code>USE SCHEMA</code>, <code>SELECT</code>/<code>MODIFY</code> on the app tables, and <code>READ VOLUME</code> on the study-file volume.</li>
              <li>A real row-filter UDF (<code>has_active_consent</code>) that gates consent-tagged rows per caller.</li>
              <li>Seed permission rows so live <code>current_user()</code> evaluation shows both granted and denied outcomes.</li>
            </ul>
          </div>
          <div>
            <div className="flex items-center gap-1.5 font-medium text-foreground">
              <KeyRound className="h-3.5 w-3.5 text-primary" /> App &amp; auth (<code>databricks.yml</code>)
            </div>
            <ul className="mt-1 space-y-1.5">
              <li><code>user_api_scopes: [sql]</code> enables on-behalf-of execution for the <code>*.obo.sql</code> queries.</li>
              <li>The serverless SQL warehouse is attached to the app as a <code>CAN_USE</code> resource.</li>
              <li>A pinned CLI profile (the workspace host matched two local profiles, which otherwise broke type generation).</li>
              <li>Dual identity: OBO (the end user) for permission-sensitive reads; the app service principal for writes and artifact generation.</li>
            </ul>
          </div>
          <div>
            <div className="flex items-center gap-1.5 font-medium text-foreground">
              <Lock className="h-3.5 w-3.5 text-primary" /> Workspace settings
            </div>
            <ul className="mt-1 space-y-1.5">
              <li>The results-download control (<code>enableResultsDownloading</code>) is read at download time to re-validate egress server-side.</li>
              <li>IP access lists where the workspace pricing tier supports them.</li>
              <li>Enable the <code>system.access</code> system schema and grant access so the platform-audit panel (<code>system.access.audit</code>) resolves (a metastore-admin step).</li>
            </ul>
          </div>
          <div>
            <div className="flex items-center gap-1.5 font-medium text-foreground">
              <Activity className="h-3.5 w-3.5 text-primary" /> Deploy
            </div>
            <ul className="mt-1 space-y-1.5">
              <li><code>databricks bundle deploy -p artdscs</code> &rarr; <code>databricks bundle run app</code>.</li>
            </ul>
          </div>
        </CardContent>
      </Card>

      <ScopeLimitNote />
    </div>
  );
}

function HomePage() {
  const { isSteward } = useContext(IdentityContext);
  const [menuOpen, setMenuOpen] = useState(true);
  const visibleLinks = EXPLORE_LINKS.filter((l) => isSteward || !STEWARD_ONLY_PATHS.has(l.to));
  const { data: requestRows, loading: requestsLoading, error: requestsError } = useAnalyticsQuery('export_requests_all', {});
  // Audit is a steward-only concern — analysts never fetch or see it.
  const { data: auditRows, loading: auditLoading, error: auditError } = useAnalyticsQuery('audit_events_all', {}, { autoStart: isSteward });

  const loading = requestsLoading || (isSteward && auditLoading);
  const error = requestsError || (isSteward ? auditError : null);
  const counts = useMemo(() => {
    if (!requestRows) return null;
    if (isSteward && !auditRows) return null;
    return {
      total: requestRows.length,
      pending: requestRows.filter((r) => r.status === 'pending').length,
      approved: requestRows.filter((r) => r.status === 'approved').length,
      rejected: requestRows.filter((r) => r.status === 'rejected').length,
      audit: auditRows?.length ?? 0,
    };
  }, [requestRows, auditRows, isSteward]);

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className={`shrink-0 ${menuOpen ? 'lg:w-56' : 'lg:w-auto'}`}>
          <div className="sticky top-6 space-y-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMenuOpen((o) => !o)}
              className="w-full justify-start gap-2"
              aria-label={menuOpen ? 'Collapse menu' : 'Expand menu'}
            >
              <Menu className="h-4 w-4" />
              {menuOpen ? 'Menu' : null}
            </Button>
            <nav className="space-y-1">
              {visibleLinks.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  title={l.label}
                  className="group flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors hover:border-primary/50 hover:bg-primary/5"
                >
                  <l.icon className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
                  {menuOpen ? <span className="font-medium">{l.label}</span> : null}
                </NavLink>
              ))}
            </nav>
          </div>
        </aside>

        <div className="min-w-0 flex-1 space-y-8">
          <div className="overflow-hidden rounded-xl border bg-gradient-to-br from-primary/10 via-primary/5 to-transparent p-6 md:p-8">
            <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-primary">
              <Database className="h-4 w-4" />
              Axle Data Export Portal
            </div>
        <h2 className="mt-2 text-3xl font-bold text-foreground">Data Exfiltration Demo in Unity Catalog</h2>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          A demonstration of how Databricks and Unity Catalog govern controlled-access research data at Axle. Every
          request is evaluated live against the requester&rsquo;s dbGaP permissions, consent group, and access tier by a{' '}
          <code>current_user()</code>-scoped Unity Catalog view, acted on by a data steward, and recorded end to end in a
          dual audit trail &mdash; no trust placed in client state, and the same consent-group check applies at the moment
          data moves through any egress path.
        </p>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Unable to load dashboard data</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading || !counts ? (
        <StatBandSkeleton />
      ) : (
        <StatBand
          stats={[
            { label: 'Total requests', value: counts.total, icon: Database, tone: 'default' },
            { label: 'Pending review', value: counts.pending, icon: Clock3, tone: 'warning' },
            { label: 'Approved', value: counts.approved, icon: CheckCircle2, tone: 'success' },
            isSteward
              ? { label: 'Audit events', value: counts.audit, icon: Activity, tone: 'primary' as const }
              : { label: 'Rejected', value: counts.rejected, icon: XCircle, tone: 'destructive' as const },
          ]}
        />
      )}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>How it works</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <div className="mb-3 flex items-center gap-2">
                <Badge variant="outline" className="border-muted-foreground/40 text-muted-foreground">
                  <ClipboardList className="mr-1 h-3.5 w-3.5" />
                  Analyst
                </Badge>
                <span className="text-xs text-muted-foreground">Requests governed exports</span>
              </div>
              <ItemGroup className="gap-2">
                <Item variant="muted">
                  <ItemMedia variant="icon">
                    <FileDown className="h-4 w-4" />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>1. Submit a request</ItemTitle>
                    <ItemDescription>
                      Choose a dataset or cohort output and provide a justification. Data outside your approved consent group is blocked automatically.
                    </ItemDescription>
                  </ItemContent>
                </Item>
                <Item variant="muted">
                  <ItemMedia variant="icon">
                    <ClipboardList className="h-4 w-4" />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>2. Track status</ItemTitle>
                    <ItemDescription>
                      Follow your requests in My Requests and access the approved governed output after steward review.
                    </ItemDescription>
                  </ItemContent>
                </Item>
              </ItemGroup>
            </div>

            <div>
              <div className="mb-3 flex items-center gap-2">
                <Badge variant="outline" className="border-primary/40 text-primary">
                  <ShieldCheck className="mr-1 h-3.5 w-3.5" />
                  Steward
                </Badge>
                <span className="text-xs text-muted-foreground">Approves or denies exports</span>
              </div>
              <ItemGroup className="gap-2">
                <Item variant="muted">
                  <ItemMedia variant="icon">
                    <KeyRound className="h-4 w-4" />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>1. Review access</ItemTitle>
                    <ItemDescription>
                      Check the requester's dbGaP-style permissions, consent group, dataset tier, and access decision.
                    </ItemDescription>
                  </ItemContent>
                </Item>
                <Item variant="muted">
                  <ItemMedia variant="icon">
                    <ShieldCheck className="h-4 w-4" />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>2. Approve or deny</ItemTitle>
                    <ItemDescription>Act on pending requests in the Steward Queue based on the access decision and stated justification.</ItemDescription>
                  </ItemContent>
                </Item>
                <Item variant="muted">
                  <ItemMedia variant="icon">
                    <Activity className="h-4 w-4" />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>3. Audit</ItemTitle>
                    <ItemDescription>Every submission, decision, and governed output action is recorded in the audit trail.</ItemDescription>
                  </ItemContent>
                </Item>
              </ItemGroup>
            </div>
          </div>
          <p className="mt-6 border-t pt-4 text-xs text-muted-foreground">
            This portal runs downstream of the dbGaP/DAC process. Consent, Data Access Request review, DAC approval,
            and DUA issuance are handled upstream and assumed complete for this proof of concept. The portal
            demonstrates how the resulting access decision can be enforced inside a governed Databricks environment
            before sensitive data is exposed or exported.
          </p>
        </CardContent>
      </Card>
        </div>
      </div>
    </div>
  );
}

type DecisionRow = {
  dataset_id: string;
  access_tier: string;
  dbgap_status: string;
  user_id: string;
  role: string;
  expiration_ts: number;
  decision: string;
  decision_basis: string;
};

function formatExpiry(epochSecs: number | null | undefined): string {
  if (!epochSecs) return '—';
  const d = new Date(epochSecs * 1000);
  if (Number.isNaN(d.getTime())) return '—';
  if (d.getFullYear() > 2090) return 'No expiry';
  const now = new Date();
  if (d < now) return `Expired ${d.toLocaleDateString(undefined, { dateStyle: 'medium' })}`;
  return d.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

const DECISION_STYLE: Record<string, { border: string; bg: string; text: string }> = {
  granted: { border: 'border-success/30', bg: 'bg-success/10', text: 'text-success' },
  denied: { border: 'border-destructive/30', bg: 'bg-destructive/10', text: 'text-destructive' },
  flagged_for_review: { border: 'border-warning/30', bg: 'bg-warning/10', text: 'text-warning' },
};

function PermissionWidget({
  selectedDatasetId,
  decisions,
  loading,
}: {
  selectedDatasetId: string;
  decisions: DecisionRow[];
  loading: boolean;
}) {
  if (!selectedDatasetId) return null;

  if (loading) return <Skeleton className="h-20 rounded-lg" />;

  const row = decisions.find((d) => d.dataset_id === selectedDatasetId);

  if (!row) {
    return (
      <Alert>
        <KeyRound className="h-4 w-4" />
        <AlertTitle>No permission record found</AlertTitle>
        <AlertDescription>No access decision on record for your account on this dataset.</AlertDescription>
      </Alert>
    );
  }

  const style = DECISION_STYLE[row.decision] ?? { border: 'border-border', bg: 'bg-muted', text: 'text-muted-foreground' };
  const meta = statusMeta(row.decision);
  const Icon = meta.icon;

  return (
    <div className={`rounded-lg border p-4 ${style.border} ${style.bg} ${style.text}`}>
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 h-5 w-5 shrink-0" />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="font-semibold">{meta.label}</div>
          <p className="text-sm opacity-90">{row.decision_basis}</p>
          <div className="flex flex-wrap gap-3 pt-1 text-xs opacity-80">
            <span>Tier: {row.access_tier.replace(/_/g, ' ')}</span>
            {row.role ? <span>Role: {row.role}</span> : null}
            {row.expiration_ts ? <span>Expires: {formatExpiry(row.expiration_ts)}</span> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

const FILE_PREVIEW_PAGE_SIZE = 20;

type StudyFile = { name: string; size: number };
type FilePreview = { columns: string[]; rows: Record<string, string | null>[]; total: number | null; page: number; pageSize: number };

// Map a data file's extension to an export format. Drives the auto-detected
// format on the Submit form so the request matches the dataset's real files.
function detectFormat(fileName: string): string {
  const ext = fileName.slice(fileName.lastIndexOf('.') + 1).toLowerCase();
  if (ext === 'ipynb') return 'ipynb';
  if (ext === 'parquet') return 'parquet';
  if (ext === 'json' || ext === 'jsonl') return 'json';
  if (ext === 'tsv') return 'tsv';
  return 'csv';
}

// Notebooks (.ipynb) are non-tabular; they get no row preview and may only be
// exported via Volumes.
function isNotebookFormat(fmt: string): boolean {
  return fmt === 'ipynb';
}

/**
 * Read-only, governed preview of the data files backing a dataset. Only shown
 * when the caller's export decision is 'granted'. Files and rows are fetched
 * from OBO server endpoints, so Unity Catalog enforces volume access on the
 * caller's own identity — a denial surfaces as a real access error.
 */
function DataFilePreview({
  datasetId,
  granted,
  onFormatDetected,
  onColumnsDetected,
}: {
  datasetId: string;
  granted: boolean;
  onFormatDetected?: (fmt: string) => void;
  onColumnsDetected?: (cols: string[]) => void;
}) {
  const [files, setFiles] = useState<StudyFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState('');
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // Total row count is cached per file so paging doesn't re-run count(*).
  const [totalRows, setTotalRows] = useState<number | null>(null);
  const countedRef = useRef('');
  // The artifact is generated from a directory read whose schema tracks the
  // first file, so cohort variables are lifted from that representative file.
  const representativeRef = useRef('');

  // Load the file list whenever a granted dataset is selected.
  useEffect(() => {
    if (!datasetId || !granted) {
      setFiles([]);
      setSelectedFile('');
      setPreview(null);
      setFilesError(null);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    setFilesLoading(true);
    setFilesError(null);
    setPreview(null);
    fetch(`/api/study-files?dataset=${encodeURIComponent(datasetId)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 403 ? 'forbidden' : `HTTP ${res.status}`);
        return res.json();
      })
      .then((body: { files: StudyFile[] }) => {
        if (cancelled) return;
        const list = body.files ?? [];
        setFiles(list);
        setSelectedFile(list[0]?.name ?? '');
        representativeRef.current = list[0]?.name ?? '';
        setPage(1);
        // Detect the export format from the dataset's own files.
        if (list[0]?.name) onFormatDetected?.(detectFormat(list[0].name));
      })
      .catch((e: Error) => {
        if (!cancelled) setFilesError(e.message);
      })
      .finally(() => {
        if (!cancelled) setFilesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, granted, onFormatDetected]);

  // Reset to the first row-page and clear the prior file's data when switching
  // files (different columns -> show skeletons, not the old table).
  useEffect(() => {
    setPage(1);
    setPreview(null);
    setTotalRows(null);
  }, [selectedFile]);

  // Load the current file's page whenever the file or page changes.
  useEffect(() => {
    // Notebooks are non-tabular — never request a row preview for them.
    if (!datasetId || !granted || !selectedFile || isNotebookFormat(detectFormat(selectedFile))) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError(null);
    // Only ask the server for the (expensive) total once per file.
    const fileKey = `${datasetId}:${selectedFile}`;
    const wantCount = countedRef.current !== fileKey;
    fetch(
      `/api/study-files/preview?dataset=${encodeURIComponent(datasetId)}&file=${encodeURIComponent(selectedFile)}&page=${page}&count=${wantCount ? '1' : '0'}`,
    )
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 403 ? 'forbidden' : `HTTP ${res.status}`);
        return res.json();
      })
      .then((body: FilePreview) => {
        if (cancelled) return;
        setPreview(body);
        if (body.total != null) {
          setTotalRows(body.total);
          countedRef.current = fileKey;
        }
        // Lift the representative file's columns up so the request form can
        // offer them as selectable cohort variables.
        if (body.columns?.length && selectedFile === representativeRef.current) {
          onColumnsDetected?.(body.columns);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setPreviewError(e.message);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, granted, selectedFile, page, onColumnsDetected]);

  if (!datasetId || !granted) return null;

  const total = totalRows ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / FILE_PREVIEW_PAGE_SIZE));
  const selectedIsNotebook = selectedFile ? isNotebookFormat(detectFormat(selectedFile)) : false;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4 text-primary" />
            Data files
          </CardTitle>
          {files.length > 0 ? (
            <div className="flex items-center gap-2">
              <Label htmlFor="study-file" className="text-xs text-muted-foreground">
                File
              </Label>
              <Select value={selectedFile} onValueChange={setSelectedFile}>
                <SelectTrigger id="study-file" className="w-64">
                  <SelectValue placeholder="Select a file…" />
                </SelectTrigger>
                <SelectContent>
                  {files.map((f) => (
                    <SelectItem key={f.name} value={f.name}>
                      {f.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>
        <p className="text-sm text-muted-foreground">
          Read-only preview of the governed files backing this dataset. Access is enforced by Unity Catalog on your
          identity.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {filesError ? (
          <Alert variant="destructive">
            <AlertTitle>Unable to list files</AlertTitle>
            <AlertDescription>
              {filesError === 'forbidden' ? 'You do not have Unity Catalog access to these files.' : filesError}
            </AlertDescription>
          </Alert>
        ) : filesLoading ? (
          <Skeleton className="h-9 w-full rounded-md" />
        ) : files.length === 0 ? (
          <p className="text-sm text-muted-foreground">No data files are available for this dataset.</p>
        ) : selectedIsNotebook ? (
          // Notebooks are Python source, not tabular data — no row preview.
          <div className="flex items-start gap-2 rounded-lg border border-dashed bg-muted/30 p-4 text-sm text-muted-foreground">
            <FileCode className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>
              <span className="font-medium text-foreground">{selectedFile}</span> is a Python notebook, so there is no
              tabular preview. Notebooks are governed file content and can be exported via <strong>Volumes</strong> only.
            </span>
          </div>
        ) : (
          <>
            {selectedFile ? (
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{selectedFile}</span> — Total rows:{' '}
                <span className="font-medium text-foreground">{totalRows == null ? '…' : total.toLocaleString()}</span>
              </p>
            ) : null}
            {previewError ? (
              <Alert variant="destructive">
                <AlertTitle>Unable to preview file</AlertTitle>
                <AlertDescription>
                  {previewError === 'forbidden' ? 'You do not have Unity Catalog access to these files.' : previewError}
                </AlertDescription>
              </Alert>
            ) : preview && preview.columns.length > 0 ? (
              // Keep the table mounted while paging; a dim overlay signals the
              // in-flight fetch instead of collapsing back to skeletons.
              <div className="relative overflow-x-auto rounded-lg border">
                {previewLoading ? (
                  <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-[1px]">
                    <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : null}
                <Table>
                  <TableHeader>
                    <TableRow>
                      {preview.columns.map((c) => (
                        <TableHead key={c} className="whitespace-nowrap">
                          {c}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.rows.map((r, idx) => (
                      <TableRow key={idx}>
                        {preview.columns.map((c) => (
                          <TableCell key={c} className="whitespace-nowrap text-sm">
                            {r[c] ?? ''}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : previewLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-9 rounded-md" />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">This file has no rows to display.</p>
            )}
            <PageNav page={page} totalPages={totalPages} onPageChange={setPage} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SubmitRequestPage() {
  const { data: catalogData, loading: catalogLoading } = useAnalyticsQuery('study_catalog_all', {});
  // Parameterless + OBO: the view resolves decisions with current_user() —
  // the caller's real UC identity — so there is nothing client-supplied to trust.
  const { data: decisionData, loading: decisionsLoading } = useAnalyticsQuery('export_decision', {});

  const [dataset, setDataset] = useState('');
  const [justification, setJustification] = useState('');
  const [format, setFormat] = useState('csv');
  const [errors, setErrors] = useState<{ dataset?: string; justification?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [messageTone, setMessageTone] = useState<'success' | 'error'>('success');
  // The shareable "Query ID" for the most recent submission.
  const [queryId, setQueryId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const decisions = (decisionData ?? []) as DecisionRow[];
  const selectedDecision = dataset ? decisions.find((d) => d.dataset_id === dataset) : undefined;
  const isDenied = selectedDecision?.decision === 'denied';
  const isGranted = selectedDecision?.decision === 'granted';

  // Format follows the selected dataset; reset on change.
  useEffect(() => {
    setFormat('csv');
  }, [dataset]);

  const validate = () => {
    const nextErrors: { dataset?: string; justification?: string } = {};
    if (!dataset.trim()) nextErrors.dataset = 'Select a dataset.';
    if (justification.trim().length < 12) nextErrors.justification = 'Please provide at least 12 characters of justification.';
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (isDenied) {
      setMessage('Access denied for this dataset — you cannot submit an export request.');
      setMessageTone('error');
      return;
    }
    if (!validate()) {
      setMessage('Please fix the highlighted fields before submitting.');
      setMessageTone('error');
      return;
    }

    setIsSubmitting(true);
    setMessage(null);
    setQueryId(null);

    try {
      // Submitter identity is resolved server-side from the forwarded auth
      // headers — the client never sends a user identifier.
      const res = await fetch('/api/export_requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset,
          justification,
          format,
        }),
      });
      const body = await res.json().catch(() => null);
      if (res.ok) {
        setMessage('Request submitted successfully.');
        setMessageTone('success');
        setQueryId(body?.id ?? null);
        setDataset('');
        setJustification('');
        setFormat('csv');
        setErrors({});
      } else if (res.status === 403) {
        setMessage('Blocked server-side: your Unity Catalog export decision for this dataset is not "granted".');
        setMessageTone('error');
      } else {
        setMessage(body?.error ?? 'Unable to submit request.');
        setMessageTone('error');
      }
    } catch {
      setMessage('Unable to reach the API.');
      setMessageTone('error');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-foreground">Submit Export Request</h2>
        <p className="text-sm text-muted-foreground">
          Request a controlled export from an approved, governed dataset. Access is decided by a consent-group-level Unity
          Catalog check &mdash; not a generic project approval &mdash; before the request is ever created.
        </p>
      </div>

      {/* Data access notice as a full-width horizontal banner. */}
      <div className="flex flex-col gap-2 rounded-lg border border-primary/20 bg-primary/5 p-4 sm:flex-row sm:items-center sm:gap-6">
        <div className="flex shrink-0 items-center gap-2 text-sm font-medium text-primary">
          <ShieldCheck className="h-4 w-4" />
          Data access notice
        </div>
        <div className="flex flex-col gap-1 text-sm text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6">
          <span>Requests are limited to approved, governed datasets.</span>
          <span>A data steward reviews every request before any output is generated.</span>
          <span>All submissions and decisions are recorded in the audit trail.</span>
        </div>
      </div>

      {/* Request form beside the data-file preview. */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="shadow-sm">
          <CardContent className="pt-6">
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="dataset">Dataset</Label>
                {catalogLoading ? (
                  <Skeleton className="h-9 w-full rounded-md" />
                ) : (
                  <Select value={dataset} onValueChange={setDataset}>
                    <SelectTrigger id="dataset" className="w-full">
                      <SelectValue placeholder="Select a dataset…" />
                    </SelectTrigger>
                    <SelectContent>
                      {(catalogData ?? []).map((s) => (
                        <SelectItem key={s.dataset_id} value={s.dataset_id}>
                          <span className="font-medium">{s.study_name}</span>
                          <span className="ml-2 text-xs text-muted-foreground">{s.dataset_id}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                {errors.dataset ? <p className="text-sm text-destructive">{errors.dataset}</p> : null}
              </div>

              <PermissionWidget selectedDatasetId={dataset} decisions={decisions} loading={decisionsLoading} />

              <div className="space-y-1.5">
                <Label htmlFor="justification">Justification</Label>
                <Textarea id="justification" value={justification} onChange={(e) => setJustification(e.target.value)} rows={4} />
                {errors.justification ? <p className="text-sm text-destructive">{errors.justification}</p> : null}
              </div>
              <div className="space-y-1.5">
                <Label>Format</Label>
                <div className="flex items-center gap-2">
                  <FormatBadge format={format} />
                  <span className="text-xs text-muted-foreground">
                    {isGranted ? 'Auto-detected from dataset files' : 'Detected from the dataset once access is granted'}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <Button type="submit" disabled={isSubmitting || isDenied}>
                  {isSubmitting ? 'Submitting…' : 'Submit'}
                </Button>
                {isDenied ? (
                  <span className="text-sm text-destructive">Access denied for this dataset — you cannot submit an export request.</span>
                ) : message && !queryId ? (
                  <span className={`text-sm ${messageTone === 'success' ? 'text-success' : 'text-destructive'}`}>{message}</span>
                ) : null}
              </div>
            </form>

            {/* Query ID: a shareable pointer to the request — not the data.
                The artifact materializes only after a steward approves. */}
            {queryId ? (
              <div className="mt-4 rounded-lg border border-primary/20 bg-primary/5 p-3">
                <div className="flex items-center gap-2 text-sm font-medium text-primary">
                  <Fingerprint className="h-4 w-4" />
                  Request submitted — Query ID
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 text-xs">{queryId}</code>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(queryId).then(
                        () => {
                          setCopied(true);
                          setTimeout(() => setCopied(false), 1500);
                        },
                        () => undefined,
                      );
                    }}
                  >
                    <Copy className="mr-1 h-3.5 w-3.5" />
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Share this pointer, not a file. Data is materialized as a governed artifact only when a steward
                  approves &mdash; then it is available under <NavLink to="/my-requests" className="font-medium text-primary underline-offset-2 hover:underline">My Requests</NavLink>.
                </p>
              </div>
            ) : null}
          </CardContent>
        </Card>

        {isGranted ? (
          <DataFilePreview datasetId={dataset} granted onFormatDetected={setFormat} />
        ) : (
          <Card className="border-dashed shadow-sm">
            <CardContent className="flex h-full min-h-48 items-center justify-center p-6 text-center text-sm text-muted-foreground">
              {dataset
                ? 'Data file preview appears here once access to the selected dataset is granted.'
                : 'Select a granted dataset to preview its data files here.'}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function MyRequestsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  // OBO + WHERE submitter = current_user(): the warehouse scopes rows to the
  // caller's real identity — no client-supplied submitter parameter. Served
  // from the uncached live endpoint (+ light polling) so a just-submitted
  // request shows up immediately instead of waiting out the analytics cache.
  const {
    data,
    loading: isLoading,
    error,
    refresh,
    refreshing,
  } = useLiveResource<{ request_id: string } & Record<string, unknown>>('/api/my-requests', { intervalMs: 20000 });
  const rows = useMemo(() => (data ?? []).map(toRequestRow), [data]);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter]);

  const filteredRows = rows.filter((r) => {
    if (statusFilter !== 'all' && r.status !== statusFilter) return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return r.dataset.toLowerCase().includes(q) || r.justification.toLowerCase().includes(q);
  });

  const counts = {
    total: rows.length,
    pending: rows.filter((r) => r.status === 'pending').length,
    approved: rows.filter((r) => r.status === 'approved').length,
    rejected: rows.filter((r) => r.status === 'rejected').length,
  };

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-2xl font-semibold text-foreground">My Export Requests</h2>
          <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Track the status of the export requests you have submitted and download approved output.
        </p>
      </div>

      {isLoading ? (
        <StatBandSkeleton />
      ) : (
        <StatBand
          stats={[
            { label: 'Total requests', value: counts.total, icon: Database, tone: 'default' },
            { label: 'Pending', value: counts.pending, icon: Clock3, tone: 'warning' },
            { label: 'Approved', value: counts.approved, icon: CheckCircle2, tone: 'success' },
            { label: 'Rejected', value: counts.rejected, icon: XCircle, tone: 'destructive' },
          ]}
        />
      )}

      <SearchFilterBar search={search} onSearchChange={setSearch} placeholder="Search by dataset or justification">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-44">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
          </SelectContent>
        </Select>
      </SearchFilterBar>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Unable to load requests</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : pageRows.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Inbox className="h-5 w-5" />
            </EmptyMedia>
            <EmptyTitle>{rows.length === 0 ? 'No requests yet' : 'No requests match your filters'}</EmptyTitle>
            <EmptyDescription>
              {rows.length === 0 ? 'Submit your first export request to see it here.' : 'Try a different search term or status filter.'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ItemGroup className="gap-2">
          {pageRows.map((r) => {
            const expired = r.expires_at ? Date.now() > new Date(r.expires_at).getTime() : false;
            const hasArtifact = Boolean(r.output_url);
            // Notebooks never materialize a tabular artifact, but an approved
            // notebook request can still be exported via Volumes.
            const showExport = hasArtifact || (isNotebookFormat(r.format) && r.status === 'approved');
            return (
              <Item key={r.id} variant="outline">
                <ItemMedia variant="icon">
                  <Database className="h-4 w-4" />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle className="flex flex-wrap items-center gap-2">
                    {r.dataset}
                    <StatusBadge status={r.status} />
                    <FormatBadge format={r.format} />
                    {hasArtifact && expired ? (
                      <Badge variant="outline" className="text-destructive border-destructive/40">
                        Expired
                      </Badge>
                    ) : null}
                  </ItemTitle>
                  <ItemDescription>{r.justification}</ItemDescription>
                  {(() => {
                    const cols = parseCohortColumns(r.selected_columns);
                    const filter = parseCohortFilter(r.cohort_filter);
                    if (cols.length === 0 && !filter) return null;
                    return (
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                        {cols.length > 0 ? (
                          <Badge variant="outline" className="font-normal">
                            <Columns3 className="mr-1 h-3 w-3" />
                            {cols.length} variable{cols.length === 1 ? '' : 's'}
                          </Badge>
                        ) : null}
                        {filter ? (
                          <Badge variant="outline" className="font-normal">
                            <Filter className="mr-1 h-3 w-3" />
                            {describeCohortFilter(filter)}
                          </Badge>
                        ) : null}
                      </div>
                    );
                  })()}
                  <div className="mt-1 text-xs text-muted-foreground">
                    Submitted {formatDate(r.created_at)}
                    {r.steward_comment ? ` · Steward note: ${r.steward_comment}` : ''}
                    {hasArtifact && r.expires_at
                      ? ` · ${expired ? 'Expired' : 'Expires'} ${formatDate(r.expires_at)}`
                      : ''}
                  </div>
                </ItemContent>
                {showExport ? (
                  <ItemActions className="items-start">
                    <ExportPathSelector req={r} />
                  </ItemActions>
                ) : null}
              </Item>
            );
          })}
        </ItemGroup>
      )}

      <PageNav page={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
}

function StewardQueuePage() {
  // Row-filtered in Unity Catalog: governed.default.steward_queue returns
  // zero rows unless is_account_group_member('bdc-stewards') is true for the
  // OBO caller — regardless of what the app requests. Read via the uncached
  // live endpoint (not the 1-hour-cached analytics path) and poll so newly
  // submitted requests appear without a reload.
  const {
    data,
    loading: isLoading,
    error: queryError,
    refresh,
    refreshing,
  } = useLiveResource<{ request_id: string } & Record<string, unknown>>('/api/steward-queue', { intervalMs: 15000 });
  const [page, setPage] = useState(1);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<StewardRequestRow | null>(null);

  const error = queryError || actionError;
  const rows = useMemo(
    () => (data ?? []).map(toStewardRow).filter((r) => !dismissedIds.has(r.id)),
    [data, dismissedIds],
  );

  useEffect(() => {
    setPage(1);
  }, [rows.length, search]);

  const filteredRows = rows.filter((r) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return r.dataset.toLowerCase().includes(q) || r.submitter.toLowerCase().includes(q) || r.justification.toLowerCase().includes(q);
  });

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Steward identity is resolved server-side from forwarded headers, and the
  // server re-verifies bdc-stewards membership with the caller's credentials.
  async function act(id: string, kind: 'approve' | 'reject') {
    setBusyId(id);
    setActionError(null);
    try {
      const res = await fetch(`/api/export_requests/${id}/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comment: kind === 'reject' ? 'Rejected in demo' : '' }),
      });
      if (res.status === 403) {
        setActionError('Blocked server-side: your account is not a member of bdc-stewards.');
        return;
      }
      if (!res.ok) {
        setActionError(`Unable to ${kind} the request.`);
        return;
      }
      setDismissedIds((current) => new Set(current).add(id));
      setSelected((current) => (current?.id === id ? null : current));
      // Re-pull from the server so the queue reflects the committed change
      // (and any requests submitted since the last poll).
      void refresh();
    } catch {
      setActionError(`Unable to ${kind} the request.`);
    } finally {
      setBusyId(null);
    }
  }

  const approve = (id: string) => act(id, 'approve');
  const reject = (id: string) => act(id, 'reject');

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-2xl font-semibold text-foreground">Steward Queue</h2>
          <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Review pending export requests and approve or reject them. The queue refreshes automatically and on demand.
        </p>
      </div>

      <Card className="border-warning/30 bg-warning/5 shadow-sm">
        <CardContent className="flex items-center gap-3 p-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-warning/15 text-warning">
            <Clock3 className="h-4 w-4" />
          </div>
          <div>
            <div className="text-2xl font-semibold leading-none text-foreground">{rows.length}</div>
            <div className="mt-1 text-xs text-muted-foreground">Requests awaiting review</div>
          </div>
        </CardContent>
      </Card>

      <SearchFilterBar search={search} onSearchChange={setSearch} placeholder="Search by dataset or submitter" />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Something went wrong</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
      ) : pageRows.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ClipboardList className="h-5 w-5" />
            </EmptyMedia>
            <EmptyTitle>{rows.length === 0 ? 'No pending requests' : 'No requests match your search'}</EmptyTitle>
            <EmptyDescription>
              {rows.length === 0 ? 'New export requests will appear here for review.' : 'Try a different search term.'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ItemGroup className="gap-2">
          {pageRows.map((r) => (
            <Item key={r.id} variant="outline">
              <ItemMedia variant="icon">
                <Database className="h-4 w-4" />
              </ItemMedia>
              <ItemContent>
                <ItemTitle className="flex flex-wrap items-center gap-2">
                  {r.study_name || r.dataset}
                  <FormatBadge format={r.format} />
                  {r.submitter_decision ? <StatusBadge status={r.submitter_decision} /> : null}
                </ItemTitle>
                <ItemDescription>{r.justification}</ItemDescription>
                <div className="mt-1 text-xs text-muted-foreground">
                  Submitted by {r.submitter} · {formatDate(r.created_at)}
                </div>
              </ItemContent>
              <ItemActions>
                <Button size="sm" variant="outline" onClick={() => setSelected(r)}>
                  <Search className="mr-1.5 h-3.5 w-3.5" />
                  View details
                </Button>
                <Button
                  size="sm"
                  className="bg-success text-success-foreground hover:bg-success/90"
                  onClick={() => approve(r.id)}
                  disabled={busyId === r.id}
                >
                  {busyId === r.id ? 'Working…' : 'Approve'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10"
                  onClick={() => reject(r.id)}
                  disabled={busyId === r.id}
                >
                  {busyId === r.id ? 'Working…' : 'Reject'}
                </Button>
              </ItemActions>
            </Item>
          ))}
        </ItemGroup>
      )}

      <PageNav page={page} totalPages={totalPages} onPageChange={setPage} />

      <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          {selected ? (
            <>
              <DialogHeader>
                <DialogTitle className="flex flex-wrap items-center gap-2">
                  {selected.study_name || selected.dataset}
                  <FormatBadge format={selected.format} />
                </DialogTitle>
                <DialogDescription>
                  Dataset <span className="font-mono">{selected.dataset}</span> · Request{' '}
                  <span className="font-mono">{selected.id}</span>
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-5 text-sm">
                <section className="space-y-2">
                  <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <User className="h-3.5 w-3.5" /> Requester
                  </h4>
                  <dl className="grid grid-cols-3 gap-x-3 gap-y-1">
                    <dt className="text-muted-foreground">Account</dt>
                    <dd className="col-span-2 break-all font-medium text-foreground">{selected.submitter}</dd>
                    <dt className="text-muted-foreground">dbGaP role</dt>
                    <dd className="col-span-2 text-foreground">{selected.submitter_role || 'None on file'}</dd>
                    <dt className="text-muted-foreground">Permission expiry</dt>
                    <dd className="col-span-2 text-foreground">{formatExpiry(selected.submitter_expiration_ts)}</dd>
                  </dl>
                </section>

                <Separator />

                <section className="space-y-2">
                  <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <ShieldCheck className="h-3.5 w-3.5" /> DAR status for this dataset
                  </h4>
                  <div className="flex flex-wrap items-center gap-2">
                    {selected.submitter_decision ? (
                      <StatusBadge status={selected.submitter_decision} />
                    ) : (
                      <span className="text-muted-foreground">Unknown</span>
                    )}
                    <span className="text-xs text-muted-foreground">live decision, re-evaluated now</span>
                  </div>
                  {selected.submitter_decision_basis ? (
                    <p className="text-muted-foreground">{selected.submitter_decision_basis}</p>
                  ) : null}
                  <dl className="grid grid-cols-3 gap-x-3 gap-y-1">
                    <dt className="text-muted-foreground">Access tier</dt>
                    <dd className="col-span-2 text-foreground">{(selected.access_tier || '—').replace(/_/g, ' ')}</dd>
                    <dt className="text-muted-foreground">dbGaP status</dt>
                    <dd className="col-span-2 text-foreground">{selected.dbgap_status || '—'}</dd>
                    <dt className="text-muted-foreground">Consent group</dt>
                    <dd className="col-span-2 text-foreground">{selected.consent_group || '—'}</dd>
                  </dl>
                </section>

                <Separator />

                <section className="space-y-2">
                  <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <ClipboardList className="h-3.5 w-3.5" /> Request details
                  </h4>
                  <dl className="grid grid-cols-3 gap-x-3 gap-y-1">
                    <dt className="text-muted-foreground">Format</dt>
                    <dd className="col-span-2 text-foreground">{selected.format}</dd>
                    <dt className="text-muted-foreground">Submitted</dt>
                    <dd className="col-span-2 text-foreground">{formatDate(selected.created_at)}</dd>
                  </dl>
                  <div>
                    <div className="text-muted-foreground">Justification</div>
                    <p className="mt-1 whitespace-pre-wrap rounded-md border bg-muted/40 p-2 text-foreground">
                      {selected.justification}
                    </p>
                  </div>
                </section>

                <section className="space-y-2">
                  <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Columns3 className="h-3.5 w-3.5" /> Requested export (cohort)
                  </h4>
                  {(() => {
                    const cols = parseCohortColumns(selected.selected_columns);
                    const filter = parseCohortFilter(selected.cohort_filter);
                    return (
                      <dl className="grid grid-cols-3 gap-x-3 gap-y-1">
                        <dt className="text-muted-foreground">Variables</dt>
                        <dd className="col-span-2 text-foreground">
                          {cols.length === 0 ? 'All variables' : cols.join(', ')}
                        </dd>
                        <dt className="text-muted-foreground">Row filter</dt>
                        <dd className="col-span-2 text-foreground">
                          {filter ? <code>{describeCohortFilter(filter)}</code> : 'None (all rows)'}
                        </dd>
                        <dt className="text-muted-foreground">Consent tagging</dt>
                        <dd className="col-span-2 text-muted-foreground">
                          Consent group + access context are appended to every exported row.
                        </dd>
                      </dl>
                    );
                  })()}
                </section>
              </div>

              <DialogFooter className="gap-2 sm:justify-between">
                <DialogClose asChild>
                  <Button variant="ghost" size="sm">
                    Close
                  </Button>
                </DialogClose>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-destructive/40 text-destructive hover:bg-destructive/10"
                    onClick={() => reject(selected.id)}
                    disabled={busyId === selected.id}
                  >
                    {busyId === selected.id ? 'Working…' : 'Reject'}
                  </Button>
                  <Button
                    size="sm"
                    className="bg-success text-success-foreground hover:bg-success/90"
                    onClick={() => approve(selected.id)}
                    disabled={busyId === selected.id}
                  >
                    {busyId === selected.id ? 'Working…' : 'Approve'}
                  </Button>
                </div>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AuditPage() {
  const { data, loading: isLoading, error } = useAnalyticsQuery('audit_events_all', {});
  const rows: AuditRow[] = data ?? [];
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState('all');

  useEffect(() => {
    setPage(1);
  }, [search, outcomeFilter]);

  const filteredRows = rows.filter((a) => {
    if (outcomeFilter !== 'all' && a.outcome !== outcomeFilter) return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return a.user.toLowerCase().includes(q) || a.action_type.toLowerCase().includes(q) || a.resource.toLowerCase().includes(q);
  });

  const counts = {
    total: rows.length,
    submitted: rows.filter((a) => a.outcome === 'submitted').length,
    approved: rows.filter((a) => a.outcome === 'approved').length,
    rejected: rows.filter((a) => a.outcome === 'rejected').length,
  };

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-foreground">Audit Log</h2>
        <p className="text-sm text-muted-foreground">
          Every submission, approval, and rejection across all users is recorded here.
        </p>
      </div>

      {isLoading ? (
        <StatBandSkeleton />
      ) : (
        <StatBand
          stats={[
            { label: 'Total events', value: counts.total, icon: Activity, tone: 'default' },
            { label: 'Submitted', value: counts.submitted, icon: FileDown, tone: 'primary' },
            { label: 'Approved', value: counts.approved, icon: CheckCircle2, tone: 'success' },
            { label: 'Rejected', value: counts.rejected, icon: XCircle, tone: 'destructive' },
          ]}
        />
      )}

      <div className="pt-2">
        <h3 className="text-lg font-semibold text-foreground">App-Reported Events</h3>
        <p className="text-sm text-muted-foreground">
          Application-level events this app writes to <code>governed.default.audit_events</code> &mdash; the workflow
          narrative. Cross-check it against the platform-level trail below.
        </p>
      </div>

      <SearchFilterBar search={search} onSearchChange={setSearch} placeholder="Search by user, action, or resource">
        <Select value={outcomeFilter} onValueChange={setOutcomeFilter}>
          <SelectTrigger className="w-full sm:w-44">
            <SelectValue placeholder="All outcomes" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All outcomes</SelectItem>
            <SelectItem value="submitted">Submitted</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
            <SelectItem value="blocked">Blocked</SelectItem>
            <SelectItem value="allowed">Allowed</SelectItem>
          </SelectContent>
        </Select>
      </SearchFilterBar>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Unable to load audit events</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 rounded-md" />
          ))}
        </div>
      ) : pageRows.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Inbox className="h-5 w-5" />
            </EmptyMedia>
            <EmptyTitle>{rows.length === 0 ? 'No audit activity yet' : 'No events match your filters'}</EmptyTitle>
            <EmptyDescription>
              {rows.length === 0 ? 'Actions taken across the app will show up here.' : 'Try a different search term or outcome filter.'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Timestamp</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Resource</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageRows.map((a) => (
                <TableRow key={a.event_id}>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">{formatDate(a.timestamp)}</TableCell>
                  <TableCell className="text-sm font-medium text-foreground">{a.user}</TableCell>
                  <TableCell className="text-sm">{a.action_type}</TableCell>
                  <TableCell className="max-w-[180px] truncate text-sm" title={a.resource}>
                    {a.resource}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={a.outcome} />
                  </TableCell>
                  <TableCell className="max-w-[220px] truncate text-xs text-muted-foreground" title={detailsToString(a.details)}>
                    {detailsToString(a.details)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <PageNav page={page} totalPages={totalPages} onPageChange={setPage} />

      <PlatformAuditPanel />

      <ScopeLimitNote />
    </div>
  );
}

/**
 * Platform Audit Log — Unity Catalog's own audit trail (system.access.audit),
 * independent of anything this app writes. Query runs OBO, so UC enforces
 * system-table access per caller; the panel is only rendered for stewards.
 */
type SystemAuditRow = {
  event_time: string;
  user_email: string;
  service_name: string;
  action_name: string;
  target: string;
  status_code: string;
};

function PlatformAuditPanel() {
  const { isSteward, loading: identityLoading } = useContext(IdentityContext);
  // Read via an uncached OBO endpoint that polls past the 30s warehouse
  // wait_timeout, so a slow system.access.audit query resolves instead of
  // surfacing as an empty/failed panel (the previous behavior).
  const { data, loading, error, refresh, refreshing } = useLiveResource<SystemAuditRow>('/api/platform-audit');
  const [page, setPage] = useState(1);

  if (identityLoading || !isSteward) return null;

  const rows = data ?? [];
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="space-y-4 pt-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <Database className="h-4 w-4 text-primary" />
            Platform Audit Log
            <Badge variant="outline" className="border-primary/40 text-[10px] uppercase tracking-wide text-primary">
              system.access.audit
            </Badge>
          </h3>
          <p className="text-sm text-muted-foreground">
            Unity Catalog's built-in audit log, filtered to governed.default objects — recorded by the platform, not by
            this app. Platform log may lag several minutes.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Unable to load the platform audit log</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 rounded-md" />
          ))}
        </div>
      ) : rows.length === 0 && !error ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Inbox className="h-5 w-5" />
            </EmptyMedia>
            <EmptyTitle>No platform events yet</EmptyTitle>
            <EmptyDescription>
              Unity Catalog events on governed.default objects from the last 30 days will appear here (delivery can lag
              several minutes).
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event time</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Service</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageRows.map((a, i) => (
                <TableRow key={`${a.event_time}-${i}`}>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">{formatDate(a.event_time)}</TableCell>
                  <TableCell className="max-w-[180px] truncate text-sm font-medium text-foreground" title={a.user_email}>
                    {a.user_email || '—'}
                  </TableCell>
                  <TableCell className="text-sm">{a.service_name}</TableCell>
                  <TableCell className="text-sm">{a.action_name}</TableCell>
                  <TableCell className="max-w-[220px] truncate font-mono text-xs" title={a.target}>
                    {a.target || '—'}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={
                        (a.status_code ?? '').startsWith('2')
                          ? 'border-success/30 bg-success/10 text-success'
                          : 'border-destructive/30 bg-destructive/10 text-destructive'
                      }
                    >
                      {a.status_code || '—'}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <PageNav page={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
}

