// Documentation artwork only. Requires macOS, Swift and ffmpeg to regenerate.
// swift docs/assets/render_pipeline.swift <frame-directory> <poster-path>
import AppKit
import CoreGraphics
import Foundation
import ImageIO

let width = 1280
let height = 800
let frameDirectory = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "/private/tmp/spend-pipeline-frames"
let posterPath = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "docs/assets/pipeline-overview.png"
try FileManager.default.createDirectory(atPath: frameDirectory, withIntermediateDirectories: true)

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(calibratedRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: alpha)
}
let ink = color(0xEDF3FF), muted = color(0x95A7C8), teal = color(0x59E0C4)
let violet = color(0xAD9BFF), gold = color(0xF6CB78)
func rect(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
    CGRect(x: x, y: CGFloat(height) - y - h, width: w, height: h)
}
func rounded(_ context: CGContext, _ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat,
             _ radius: CGFloat, _ fill: NSColor, _ stroke: NSColor? = nil, _ lineWidth: CGFloat = 1) {
    let path = CGPath(roundedRect: rect(x, y, w, h), cornerWidth: radius, cornerHeight: radius, transform: nil)
    context.addPath(path); context.setFillColor(fill.cgColor); context.fillPath()
    if let stroke = stroke {
        context.addPath(path); context.setStrokeColor(stroke.cgColor); context.setLineWidth(lineWidth); context.strokePath()
    }
}
func text(_ value: String, _ x: CGFloat, _ y: CGFloat, _ size: CGFloat,
          _ weight: NSFont.Weight = .regular, _ foreground: NSColor = ink, _ mono: Bool = false) {
    let font = mono ? NSFont.monospacedSystemFont(ofSize: size, weight: weight) : NSFont.systemFont(ofSize: size, weight: weight)
    let attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: foreground]
    (value as NSString).draw(in: rect(x, y, 1210 - x, size * 1.55), withAttributes: attributes)
}
func line(_ context: CGContext, _ points: [(CGFloat, CGFloat)], _ stroke: NSColor, _ thickness: CGFloat = 1.5) {
    guard let start = points.first else { return }
    context.beginPath(); context.move(to: CGPoint(x: start.0, y: CGFloat(height) - start.1))
    for point in points.dropFirst() { context.addLine(to: CGPoint(x: point.0, y: CGFloat(height) - point.1)) }
    context.setLineCap(.round); context.setLineJoin(.round); context.setStrokeColor(stroke.cgColor)
    context.setLineWidth(thickness); context.strokePath()
}
func dot(_ context: CGContext, _ x: CGFloat, _ y: CGFloat, _ radius: CGFloat, _ fill: NSColor) {
    context.setFillColor(fill.cgColor); context.fillEllipse(in: rect(x-radius,y-radius,radius*2,radius*2))
}
func pill(_ context: CGContext, _ label: String, _ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ accent: NSColor) {
    rounded(context,x,y,w,34,17,color(0x14223A),accent.withAlphaComponent(0.35))
    dot(context,x+15,y+17,3,accent);text(label,x+26,y+8,12,.medium,accent,true)
}
func draw(_ time: Double) -> CGImage {
    let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    let background = CGPath(roundedRect: rect(0,0,1280,800),cornerWidth:28,cornerHeight:28,transform:nil)
    context.setFillColor(color(0x0A1020).cgColor);context.fill(rect(0,0,1280,800))
    context.addPath(background);context.clip()
    let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                              colors: [color(0x0A1020).cgColor,color(0x14233B).cgColor] as CFArray,locations:[0,1])!
    context.drawLinearGradient(gradient,start:CGPoint(x:0,y:800),end:CGPoint(x:1280,y:0),options:[])
    for x in stride(from:32,through:1248,by:32) {
        for y in stride(from:32,through:768,by:32) { dot(context,CGFloat(x),CGFloat(y),0.65,color(0x8DA7D2,0.10)) }
    }
    NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(cgContext:context,flipped:false)
    for i in 0..<3 { rounded(context,56+CGFloat(i)*5,49-CGFloat(i)*5,20,7,3,teal.withAlphaComponent(CGFloat(0.4+Double(i)*0.3))) }
    text("SPEND PIPELINE",99,43,17,.semibold,ink,true)
    pill(context,"PYTHON",803,41,106,teal)
    pill(context,"LOCAL",921,41,100,violet)
    pill(context,"CONFIG DRIVEN",1033,41,191,gold)
    text("From raw records",56,105,50,.bold)
    text("to classified spend.",56,164,50,.bold,teal)
    text("One config. A runtime taxonomy. A validated CSV.",58,236,19,.regular,muted)
    // Three inputs feed the process. These are conceptual sources, not row data.
    pill(context,"PURCHASE FILES",56,294,230,teal)
    pill(context,"COMPANY CONFIG",423,294,230,violet)
    pill(context,"RUNTIME TAXONOMY",895,294,277,gold)
    line(context,[(171,328),(171,346),(162,346),(162,364)],teal.withAlphaComponent(0.5))
    line(context,[(538,328),(538,346),(208,346),(208,364)],violet.withAlphaComponent(0.45))
    line(context,[(1033,328),(1033,346),(878,346),(878,364)],gold.withAlphaComponent(0.5))
    let titles=["Ingest","Normalize","Resolve","Classify","Export"]
    let first=["Map source columns","Net tax + FX","Supplier / item keys","Runtime leaf paths","Contract checks"]
    let second=["Apply source rules","Signed amounts","Conservative matches","Local model options","CSV + private audit"]
    let accents=[teal,teal,violet,gold,teal]
    let progress = min(4.95,time * 5.45)
    for i in 0..<5 {
        let x=56+CGFloat(i)*239
        let energy=exp(-pow(Double(i)+0.45-progress,2)/0.20)
        let accent=accents[i]
        if energy>0.01 {
            context.saveGState();context.setShadow(offset:.zero,blur:19,color:accent.withAlphaComponent(CGFloat(energy*0.22)).cgColor)
            rounded(context,x,364,212,174,18,color(0x15243C),accent.withAlphaComponent(CGFloat(0.2+energy*0.7)),CGFloat(1+energy))
            context.restoreGState()
        } else { rounded(context,x,364,212,174,18,color(0x122037),color(0x2B3B57)) }
        rounded(context,x+17,381,33,25,7,accent.withAlphaComponent(0.12))
        text(String(format:"%02d",i+1),x+23,384,12,.semibold,accent,true)
        dot(context,x+187,393,3.5,accent.withAlphaComponent(CGFloat(0.25+energy*0.75)))
        text(titles[i],x+17,419,24,.semibold)
        text(first[i],x+17,465,14,.regular,muted)
        text(second[i],x+17,488,14,.regular,muted)
        rounded(context,x+17,523,178,2,1,color(0x253650))
        let fraction=max(0,min(1,progress-Double(i)+0.2))
        if fraction>0 { rounded(context,x+17,523,CGFloat(fraction)*178,2,1,accent) }
        if i<4 {
            line(context,[(x+215,450),(x+234,450)],color(0x526A8F),1.4)
            line(context,[(x+229,446),(x+234,450),(x+229,454)],color(0x7A93B8),1.4)
            let travel=(time*4.0-Double(i)*0.15).truncatingRemainder(dividingBy:1)
            if travel>=0 { dot(context,x+215+CGFloat(travel)*19,450,2.8,accent.withAlphaComponent(0.85)) }
        }
    }
    line(context,[(1118,542),(1118,565),(640,565),(640,587)],teal.withAlphaComponent(0.45))
    rounded(context,56,589,1168,135,18,color(0x0E1B2E),color(0x2D425D))
    text("ONE OUTPUT CSV",78,609,13,.semibold,ink,true)
    text("Every input row stays traceable",78,637,19,.medium)
    line(context,[(495,608),(495,703)],color(0x2B3C55),1)
    dot(context,522,623,4,teal);text("INCLUDED",535,613,12,.semibold,teal,true)
    text("Net spend, keys and",519,642,16,.regular,muted)
    text("a valid category path",519,665,16,.regular,muted)
    line(context,[(825,608),(825,703)],color(0x2B3C55),1)
    dot(context,852,623,4,gold);text("EXCLUDED",865,613,12,.semibold,gold,true)
    text("Reason code, zero spend",849,642,16,.regular,muted)
    text("and blank categories",849,665,16,.regular,muted)
    text("RUNTIME CONFIG",58,756,11,.medium,muted,true)
    text("LOCAL INFERENCE",437,756,11,.medium,muted,true)
    text("PRIVATE DIAGNOSTICS STAY LOCAL",827,756,11,.medium,muted,true)
    NSGraphicsContext.restoreGraphicsState()
    return context.makeImage()!
}
func savePNG(_ image: CGImage,_ path: String) {
    let url=URL(fileURLWithPath:path)
    let destination=CGImageDestinationCreateWithURL(url as CFURL,"public.png" as CFString,1,nil)!
    CGImageDestinationAddImage(destination,image,nil)
    precondition(CGImageDestinationFinalize(destination),"Cannot save PNG")
}
savePNG(draw(0.43),posterPath)
for index in 0..<96 {
    autoreleasepool { savePNG(draw(Double(index)/96.0),String(format:"%@/frame-%03d.png",frameDirectory,index)) }
}
print("Rendered 96 frames and static overview.")
