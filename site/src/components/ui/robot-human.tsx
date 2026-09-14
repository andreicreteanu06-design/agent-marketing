"use client"

// AsciiArt — "Robot + Human", made with the 21st ASCII editor and baked
// to its exact rendered output (looping video + poster). Zero dependencies:
// one <video> that fills its parent. Drop it behind or inside your content:
// <div className="relative h-96"><AsciiArt className="absolute inset-0" /></div>
// Remix the source recipe (styles, animation, palette) in the editor:
// https://21st.dev/community/ascii/editor?from=25c92651-8670-4900-9f54-3f80dec789cb
export function AsciiArt({ className }: { className?: string }) {
  return (
    <video
      className={className}
      src={"https://assets.21st.dev/ascii-recipes/videos/user_3JJSuFU9CSbl5VeOKE63isvGVXQ/022d4ddb-851b-42d1-8cd2-54d42fc7c2e7.mp4"}
      poster={"https://assets.21st.dev/ascii-recipes/thumbnails/user_3JJSuFU9CSbl5VeOKE63isvGVXQ/baaf7425-6723-47c2-abdc-0997341b761f.webp"}
      autoPlay
      loop
      muted
      playsInline
      aria-label={"Robot + Human: animated ASCII art"}
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        objectFit: "cover",
      }}
    />
  )
}
