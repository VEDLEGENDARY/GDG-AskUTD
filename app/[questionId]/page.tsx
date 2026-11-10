import AskUtdApp from '@/components/ask-utd-app';

export default async function QuestionPage({ params }: { params: Promise<{ questionId: string }> }) {
  const { questionId } = await params;
  return <AskUtdApp questionId={questionId} />;
}
