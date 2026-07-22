/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // smaller runtime image — only what's needed to `next start`
  reactStrictMode: true,
};

module.exports = nextConfig;
