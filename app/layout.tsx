import type { Metadata } from 'next';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import './globals.css';

export const metadata: Metadata = {
  title: { default: 'ASK-UTD | Your campus, answered', template: '%s | ASK-UTD' },
  description: 'Get clear, sourced answers to your University of Texas at Dallas questions.',
  applicationName: 'ASK-UTD',
  keywords: ['UT Dallas', 'student support', 'campus questions', 'ASK-UTD'],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
