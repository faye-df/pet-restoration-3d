import Foundation
import ImageIO
import UniformTypeIdentifiers

let frameDirectory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let fileManager = FileManager.default
let frames = try fileManager.contentsOfDirectory(
    at: frameDirectory,
    includingPropertiesForKeys: nil,
    options: [.skipsHiddenFiles]
).filter { $0.pathExtension.lowercased() == "png" }
 .sorted { $0.lastPathComponent < $1.lastPathComponent }

guard !frames.isEmpty else {
    fatalError("No PNG animation frames found at \(frameDirectory.path)")
}
guard let destination = CGImageDestinationCreateWithURL(
    outputURL as CFURL,
    UTType.gif.identifier as CFString,
    frames.count,
    nil
) else {
    fatalError("Unable to create GIF destination")
}

let gifProperties: [CFString: Any] = [
    kCGImagePropertyGIFDictionary: [
        kCGImagePropertyGIFLoopCount: 0
    ]
]
CGImageDestinationSetProperties(destination, gifProperties as CFDictionary)

let frameProperties: [CFString: Any] = [
    kCGImagePropertyGIFDictionary: [
        kCGImagePropertyGIFDelayTime: 1.0 / 24.0,
        kCGImagePropertyGIFUnclampedDelayTime: 1.0 / 24.0
    ]
]

for frameURL in frames {
    guard let source = CGImageSourceCreateWithURL(frameURL as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        fatalError("Unable to read \(frameURL.path)")
    }
    CGImageDestinationAddImage(destination, image, frameProperties as CFDictionary)
}

guard CGImageDestinationFinalize(destination) else {
    fatalError("Unable to finalize GIF")
}

print("GIF=\(outputURL.path) FRAMES=\(frames.count)")
