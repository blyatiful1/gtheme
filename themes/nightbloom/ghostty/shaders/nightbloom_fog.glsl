// NIGHTBLOOM fog — the glasshouse fogs over when you look away.
// Focus-aware (Ghostty 1.3 iFocus/iTimeFocus uniforms): the unfocused
// terminal desaturates slightly, dims 8%, and cools toward moss over
// ~0.35s. Runs after the firefly shader, so the cursor wake dims with
// everything else. rgb-only — background alpha is preserved, the glass
// survives.

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec4 c = texture(iChannel0, fragCoord.xy / iResolution.xy);

    float focused = clamp(float(iFocus), 0.0, 1.0);
    float since = clamp((iTime - iTimeFocus) / 0.35, 0.0, 1.0);
    float e = since * since * (3.0 - 2.0 * since);
    // previous fog level was the opposite of where we are heading
    float fog = mix(focused, 1.0 - focused, e);

    float gray = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 rgb = mix(c.rgb, vec3(gray), 0.35 * fog);
    rgb *= 1.0 - 0.08 * fog;
    rgb = mix(rgb, rgb * vec3(0.94, 1.02, 0.96), 0.5 * fog);

    fragColor = vec4(rgb, c.a);
}
