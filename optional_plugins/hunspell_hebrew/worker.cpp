// MIT: project-authored bridge. Hunspell and dictionaries retain their licenses.
#include <hunspell.hxx>
#include <iostream>
#include <string>

int main() {
    // Paths arrive as UTF-8 on stdin, not locale-dependent Windows argv.
    // On Windows the caller supplies Hunspell's documented \\?\ prefix.
    std::string aff, dic;
    if (!std::getline(std::cin, aff) || !std::getline(std::cin, dic) ||
        aff.size() > 32768 || dic.size() > 32768) return 2;
    Hunspell checker(aff.c_str(), dic.c_str());
    if (std::string(checker.get_dic_encoding()) != "UTF-8") {
        std::cerr << "Only UTF-8 Hunspell dictionaries are supported.\n";
        return 2;
    }
    std::cout << "HUNSPELL-HEBREW/1\n";
    std::string word;
    unsigned count = 0;
    while (std::getline(std::cin, word)) {
        if (++count > 2048 || word.empty() || word.size() > 256 ||
            word.find('\t') != std::string::npos || word.find('\r') != std::string::npos)
            return 2;
        if (checker.spell(word)) std::cout << "1\n";
        else {
            std::cout << "0";
            auto suggestions = checker.suggest(word);
            unsigned written = 0;
            for (const auto& item : suggestions) {
                if (item.empty() || item.size() > 256 ||
                    item.find_first_of("\t\r\n") != std::string::npos) continue;
                std::cout << '\t' << item;
                if (++written == 3) break;
            }
            std::cout << '\n';
        }
    }
    return std::cin.bad() ? 2 : 0;
}
