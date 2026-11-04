import type { Metadata } from 'next';
import AskUtdApp from '@/components/ask-utd-app';

const questions: Record<string, string> = {
  'androids-dream': 'Do androids dream of electric sheep or not?',
  'fbi-server': 'Hacking FBI server with raspberry pie',
  'sicp-tutorial': 'COMPsci SICP tutorial course',
  'proxy-failure-troubleshooting': 'Proxy failure troubleshooting',
  'september-ends': 'Wake me up when september ends chord',
  'oasis-songs': 'Best OASIS songs top 100 all time',
  'ssl-tls-error': 'Fix SSL/TLS Error',
  'react-component': 'React component quick fix',
  'nextjs-docs': 'Nextjs 18 documentations',
  'healthy-in-one-hour': 'How to get healthy in 1 hour',
};

export function generateStaticParams() {
  return Object.keys(questions).map((questionId) => ({ questionId }));
}

export async function generateMetadata({ params }: { params: Promise<{ questionId: string }> }): Promise<Metadata> {
  const { questionId } = await params;
  return { title: questions[questionId] ?? 'Campus questions' };
}

export default async function QuestionPage({ params }: { params: Promise<{ questionId: string }> }) {
  const { questionId } = await params;
  return <AskUtdApp questionId={questionId} questionTitle={questions[questionId] ?? 'Your campus question'} />;
}
