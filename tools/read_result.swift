import Foundation
import Vision

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
let handler = VNImageRequestHandler(url: imageURL, options: [:])
try handler.perform([request])
let observations = (request.results ?? []).compactMap { observation -> [String: Any]? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    return ["text": candidate.string, "x": box.midX, "y": 1 - box.midY]
}
let data = try JSONSerialization.data(withJSONObject: observations)
FileHandle.standardOutput.write(data)
