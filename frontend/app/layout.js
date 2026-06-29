import "./globals.css";
import "katex/dist/katex.min.css";
import "highlight.js/styles/github-dark.css";
import SideNav from "./components/SideNav";
import Notifications from "./components/Notifications";

export const metadata = {
  title: "SourceMind",
  description: "Source-grounded mastery courses",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <SideNav />
        <Notifications />
        <div className="container">{children}</div>
      </body>
    </html>
  );
}
