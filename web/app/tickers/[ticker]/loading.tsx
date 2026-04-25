export default function Loading() {
  return (
    <main className="mx-auto max-w-screen-2xl px-6 py-8">
      <div className="space-y-6">
        <div className="h-32 animate-pulse rounded-md bg-muted" />
        <div className="h-48 animate-pulse rounded-md bg-muted" />
        <div className="h-64 animate-pulse rounded-md bg-muted" />
      </div>
    </main>
  );
}
