import { useEffect, useRef } from 'react'
import { Mesh, Program, Renderer, Triangle } from 'ogl'
import './Grainient.css'

type GrainientProps = {
  color1?: string
  color2?: string
  color3?: string
  timeSpeed?: number
  colorBalance?: number
  warpStrength?: number
  warpFrequency?: number
  warpSpeed?: number
  warpAmplitude?: number
  blendAngle?: number
  blendSoftness?: number
  rotationAmount?: number
  noiseScale?: number
  grainAmount?: number
  grainScale?: number
  grainAnimated?: boolean
  contrast?: number
  gamma?: number
  saturation?: number
  centerX?: number
  centerY?: number
  zoom?: number
  className?: string
}

const vertex = `#version 300 es
in vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }
`

const fragment = `#version 300 es
precision highp float;
uniform vec2 iResolution;
uniform float iTime, uTimeSpeed, uColorBalance, uWarpStrength, uWarpFrequency;
uniform float uWarpSpeed, uWarpAmplitude, uBlendAngle, uBlendSoftness;
uniform float uRotationAmount, uNoiseScale, uGrainAmount, uGrainScale, uContrast;
uniform float uGamma, uSaturation, uZoom, uGrainAnimated;
uniform vec2 uCenterOffset;
uniform vec3 uColor1, uColor2, uColor3;
out vec4 fragColor;
#define S(a,b,t) smoothstep(a,b,t)
mat2 Rot(float a){float s=sin(a),c=cos(a);return mat2(c,-s,s,c);}
vec2 hash(vec2 p){p=vec2(dot(p,vec2(2127.1,81.17)),dot(p,vec2(1269.5,283.37)));return fract(sin(p)*43758.5453);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p),u=f*f*(3.0-2.0*f);float n=mix(mix(dot(-1.0+2.0*hash(i),f),dot(-1.0+2.0*hash(i+vec2(1.0,0.0)),f-vec2(1.0,0.0)),u.x),mix(dot(-1.0+2.0*hash(i+vec2(0.0,1.0)),f-vec2(0.0,1.0)),dot(-1.0+2.0*hash(i+vec2(1.0)),f-vec2(1.0)),u.x),u.y);return 0.5+0.5*n;}
void main(){
  float t=iTime*uTimeSpeed; vec2 uv=gl_FragCoord.xy/iResolution.xy; float ratio=iResolution.x/iResolution.y;
  vec2 tuv=(uv-0.5+uCenterOffset)/max(uZoom,0.001);
  float degree=noise(vec2(t*0.1,tuv.x*tuv.y)*uNoiseScale);
  tuv.y/=ratio; tuv*=Rot(radians((degree-0.5)*uRotationAmount+180.0)); tuv.y*=ratio;
  float amplitude=uWarpAmplitude/max(uWarpStrength,0.001), warpTime=t*uWarpSpeed;
  tuv.x+=sin(tuv.y*uWarpFrequency+warpTime)/amplitude;
  tuv.y+=sin(tuv.x*(uWarpFrequency*1.5)+warpTime)/(amplitude*0.5);
  float edge0=-0.3-uColorBalance-uBlendSoftness, edge1=0.2-uColorBalance+uBlendSoftness;
  float blendX=(tuv*Rot(radians(uBlendAngle))).x;
  vec3 first=mix(uColor3,uColor2,S(edge0,edge1,blendX));
  vec3 second=mix(uColor2,uColor1,S(edge0,edge1,blendX));
  vec3 col=mix(first,second,S(0.5-uColorBalance+uBlendSoftness,-0.3-uColorBalance-uBlendSoftness,tuv.y));
  vec2 grainUv=uv*uGrainScale;
  if(uGrainAnimated>0.5) grainUv+=vec2(iTime*0.05);
  float grain=fract(sin(dot(grainUv,vec2(12.9898,78.233)))*43758.5453);
  col+=(grain-0.5)*uGrainAmount; col=(col-0.5)*uContrast+0.5;
  float luma=dot(col,vec3(0.2126,0.7152,0.0722)); col=mix(vec3(luma),col,uSaturation);
  col=pow(max(col,0.0),vec3(1.0/max(uGamma,0.001)));
  fragColor=vec4(clamp(col,0.0,1.0),1.0);
}`

const rgb = (hex: string) => {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  return match ? [1, 2, 3].map((index) => parseInt(match[index], 16) / 255) : [1, 1, 1]
}

export default function Grainient({
  color1 = '#4D8BFF', color2 = '#2D62EC', color3 = '#10265F', timeSpeed = 0.2,
  colorBalance = 0, warpStrength = 0.8, warpFrequency = 4, warpSpeed = 0.8,
  warpAmplitude = 70, blendAngle = 15, blendSoftness = 0.18, rotationAmount = 100,
  noiseScale = 1.5, grainAmount = 0.035, grainScale = 2, grainAnimated = false,
  contrast = 1.12, gamma = 1, saturation = 1, centerX = 0, centerY = 0, zoom = 0.9,
  className = '',
}: GrainientProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let renderer: Renderer
    try {
      renderer = new Renderer({ webgl: 2, alpha: true, antialias: false, dpr: Math.min(window.devicePixelRatio || 1, 2) })
    } catch {
      return
    }
    const gl = renderer.gl
    const canvas = gl.canvas
    canvas.style.cssText = 'display:block;width:100%;height:100%;'
    container.appendChild(canvas)
    const geometry = new Triangle(gl)
    const program = new Program(gl, {
      vertex, fragment,
      uniforms: {
        iTime: { value: 0 }, iResolution: { value: new Float32Array([1, 1]) },
        uTimeSpeed: { value: timeSpeed }, uColorBalance: { value: colorBalance },
        uWarpStrength: { value: warpStrength }, uWarpFrequency: { value: warpFrequency },
        uWarpSpeed: { value: warpSpeed }, uWarpAmplitude: { value: warpAmplitude },
        uBlendAngle: { value: blendAngle }, uBlendSoftness: { value: blendSoftness },
        uRotationAmount: { value: rotationAmount }, uNoiseScale: { value: noiseScale },
        uGrainAmount: { value: grainAmount }, uGrainScale: { value: grainScale },
        uGrainAnimated: { value: grainAnimated ? 1 : 0 },
        uContrast: { value: contrast }, uGamma: { value: gamma }, uSaturation: { value: saturation },
        uCenterOffset: { value: new Float32Array([centerX, centerY]) }, uZoom: { value: zoom },
        uColor1: { value: new Float32Array(rgb(color1)) }, uColor2: { value: new Float32Array(rgb(color2)) },
        uColor3: { value: new Float32Array(rgb(color3)) },
      },
    })
    const mesh = new Mesh(gl, { geometry, program })
    const resize = () => {
      const rect = container.getBoundingClientRect()
      renderer.setSize(Math.max(1, Math.floor(rect.width)), Math.max(1, Math.floor(rect.height)))
      program.uniforms.iResolution.value.set([gl.drawingBufferWidth, gl.drawingBufferHeight])
      renderer.render({ scene: mesh })
    }
    const observer = new ResizeObserver(resize)
    observer.observe(container)
    resize()

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let frame = 0
    let visible = true
    let pageVisible = !document.hidden
    const startTime = performance.now()
    const render = (time: number) => {
      program.uniforms.iTime.value = (time - startTime) * 0.001
      renderer.render({ scene: mesh })
      frame = requestAnimationFrame(render)
    }
    const start = () => { if (!reducedMotion && visible && pageVisible && !frame) frame = requestAnimationFrame(render) }
    const stop = () => { if (frame) { cancelAnimationFrame(frame); frame = 0 } }
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      if (visible) start(); else stop()
    })
    intersection.observe(container)
    const onVisibility = () => { pageVisible = !document.hidden; if (pageVisible) start(); else stop() }
    document.addEventListener('visibilitychange', onVisibility)
    start()

    return () => {
      stop(); observer.disconnect(); intersection.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      container.removeChild(canvas)
    }
  }, [blendAngle, blendSoftness, centerX, centerY, color1, color2, color3, colorBalance, contrast, gamma, grainAmount, grainAnimated, grainScale, noiseScale, rotationAmount, saturation, timeSpeed, warpAmplitude, warpFrequency, warpSpeed, warpStrength, zoom])

  return <div ref={containerRef} className={`grainient-container ${className}`.trim()} aria-hidden="true" />
}
