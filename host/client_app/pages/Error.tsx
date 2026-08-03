type ErrorProps = {
  status: number;
  message?: string;
};

// Named ErrorPage rather than Error so it doesn't shadow the global. The
// Inertia page name comes from the filename, not the function name.
export default function ErrorPage({ status, message }: ErrorProps) {
  return (
    <main style={{ padding: '2rem', maxWidth: '40rem', margin: '0 auto' }}>
      <h1>{status}</h1>
      <p>{message || 'Something went wrong.'}</p>
    </main>
  );
}
