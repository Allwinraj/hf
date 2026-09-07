import { useEffect, useRef } from 'react'

export default function WebGLBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const gl = canvas.getContext('webgl')
    if (!gl) return

    const ctx: WebGLRenderingContext = gl
    const el: HTMLCanvasElement = canvas

    const vertexShaderSource = `
      attribute vec4 a_position;
      varying vec2 v_texCoord;
      void main() {
        gl_Position = a_position;
        v_texCoord = a_position.xy * 0.5 + 0.5;
      }
    `

    const fragmentShaderSource = `
      precision highp float;
      varying vec2 v_texCoord;
      uniform float u_time;
      uniform vec2 u_resolution;
      uniform vec2 u_mouse;
      uniform float u_light;

      float hash(vec2 p) {
        p = fract(p * vec2(123.34, 456.21));
        p += dot(p, p + 45.32);
        return fract(p.x * p.y);
      }

      float line(vec2 p, vec2 a, vec2 b) {
        vec2 pa = p - a;
        vec2 ba = b - a;
        float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
        return smoothstep(0.01, 0.0, length(pa - ba * h));
      }

      void main() {
        vec2 uv = v_texCoord;
        vec2 mouse = u_mouse / u_resolution;
        float aspect = u_resolution.x / u_resolution.y;
        vec2 p = uv * 2.0 - 1.0;
        p.x *= aspect;

        vec3 darkBg = vec3(0.078, 0.129, 0.239);
        vec3 lightBg = vec3(0.898, 0.898, 0.898);
        vec3 color = mix(darkBg, lightBg, u_light);
        vec3 gold = vec3(0.988, 0.639, 0.067);

        vec2 grid_uv = uv * 8.0;
        vec2 id = floor(grid_uv);
        vec2 f = fract(grid_uv) - 0.5;

        float m = 0.0;
        float t = u_time * 0.5;

        for(float y = -1.0; y <= 1.0; y++) {
          for(float x = -1.0; x <= 1.0; x++) {
            vec2 offs = vec2(x, y);
            float n = hash(id + offs);
            vec2 p_node = offs + sin(t + n * 6.28) * 0.4;
            float d = length(f - p_node);
            m += smoothstep(0.05, 0.0, d) * n;

            float distToMouse = length(uv - mouse);
            m += (smoothstep(0.2, 0.0, distToMouse) * 0.5);
          }
        }

        color += m * gold * mix(0.32, 0.16, u_light);

        float gx = abs(fract(uv.x * 16.0));
        float gy = abs(fract(uv.y * 16.0));
        float grid = 1.0 - smoothstep(0.0, 0.04, min(gx, gy));
        vec3 gridCol = mix(vec3(0.898, 0.898, 0.898), vec3(0.078, 0.129, 0.239), u_light);
        color = mix(color, gridCol, grid * mix(0.14, 0.2, u_light));

        float vignette = smoothstep(1.6, 0.45, length(p));
        color = mix(color, color * vignette, mix(0.85, 0.28, u_light));

        gl_FragColor = vec4(color, 1.0);
      }
    `

    function createShader(gl: WebGLRenderingContext, type: number, source: string) {
      const shader = gl.createShader(type)
      if (!shader) return null
      gl.shaderSource(shader, source)
      gl.compileShader(shader)
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader)
        return null
      }
      return shader
    }

    const vertexShader = createShader(gl, gl.VERTEX_SHADER, vertexShaderSource)
    const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, fragmentShaderSource)
    if (!vertexShader || !fragmentShader) return

    const program = gl.createProgram()
    if (!program) return
    gl.attachShader(program, vertexShader)
    gl.attachShader(program, fragmentShader)
    gl.linkProgram(program)

    const positionAttributeLocation = gl.getAttribLocation(program, 'a_position')
    const positionBuffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    )

    const timeLocation = gl.getUniformLocation(program, 'u_time')
    const resolutionLocation = gl.getUniformLocation(program, 'u_resolution')
    const mouseLocation = gl.getUniformLocation(program, 'u_mouse')
    const lightLocation = gl.getUniformLocation(program, 'u_light')

    let mouseX = 0
    let mouseY = 0
    let raf = 0

    const onMouseMove = (e: MouseEvent) => {
      mouseX = e.clientX
      mouseY = el.height - e.clientY
    }

    function resizeCanvasToDisplaySize() {
      const displayWidth = el.clientWidth
      const displayHeight = el.clientHeight
      if (el.width !== displayWidth || el.height !== displayHeight) {
        el.width = displayWidth
        el.height = displayHeight
      }
    }

    function render(time: number) {
      time *= 0.001
      resizeCanvasToDisplaySize()
      ctx.viewport(0, 0, el.width, el.height)
      ctx.useProgram(program)

      ctx.enableVertexAttribArray(positionAttributeLocation)
      ctx.bindBuffer(ctx.ARRAY_BUFFER, positionBuffer)
      ctx.vertexAttribPointer(positionAttributeLocation, 2, ctx.FLOAT, false, 0, 0)

      ctx.uniform1f(timeLocation, time)
      ctx.uniform2f(resolutionLocation, el.width, el.height)
      ctx.uniform2f(mouseLocation, mouseX, mouseY)
      const light = document.documentElement.dataset.theme === 'light' ? 1.0 : 0.0
      ctx.uniform1f(lightLocation, light)

      ctx.drawArrays(ctx.TRIANGLES, 0, 6)
      raf = requestAnimationFrame(render)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('resize', resizeCanvasToDisplaySize)
    raf = requestAnimationFrame(render)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('resize', resizeCanvasToDisplaySize)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-0 h-full w-full"
      aria-hidden="true"
    />
  )
}
