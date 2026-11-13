interface PageHeaderProps {
  title: string;
  description?: string;
}

export function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <div className="mb-6">
      <h1 className="bg-gradient-to-r from-slate-50 to-slate-300 bg-clip-text text-2xl font-semibold tracking-tight text-transparent">
        {title}
      </h1>
      {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
    </div>
  );
}
