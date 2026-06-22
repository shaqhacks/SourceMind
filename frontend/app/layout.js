import "./globals.css";
import SideNav from "./components/SideNav";

export const metadata = {
  title: "SourceMind",
  description: "Source-grounded mastery courses",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <SideNav />
        <div className="container">{children}</div>
      </body>
    </html>
  );
}
